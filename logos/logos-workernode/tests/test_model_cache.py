"""Tests for the ModelRamCache (Feature 3: tmpfs RAM cache)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from logos_worker_node.model_cache import ModelRamCache, _hf_model_dir_name, create_model_cache

# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_hf_model_dir_name():
    assert _hf_model_dir_name("Qwen/Qwen2.5-Coder-7B") == "models--Qwen--Qwen2.5-Coder-7B"
    assert _hf_model_dir_name("meta-llama/Llama-3.1-8B") == "models--meta-llama--Llama-3.1-8B"


# ---------------------------------------------------------------------------
# Disabled cache
# ---------------------------------------------------------------------------


def test_disabled_cache_factory_empty_path():
    cache = create_model_cache(tmpfs_path=None, hf_home="/tmp/hf")
    assert not cache.enabled
    assert cache.cached_models() == []


def test_disabled_cache_factory_empty_string():
    cache = create_model_cache(tmpfs_path="", hf_home="/tmp/hf")
    assert not cache.enabled


def test_disabled_cache_factory_nonexistent_path():
    cache = create_model_cache(tmpfs_path="/nonexistent/path/xyz", hf_home="/tmp/hf")
    assert not cache.enabled


# ---------------------------------------------------------------------------
# ModelRamCache with real tmpdir
# ---------------------------------------------------------------------------


@pytest.fixture
def ram_cache_env(tmp_path):
    """Set up source and tmpfs directories for testing."""
    source_hf = tmp_path / "source" / "hub"
    source_hf.mkdir(parents=True)
    tmpfs = tmp_path / "ramcache"
    tmpfs.mkdir()

    # Create a fake model in the source
    model_dir = source_hf / "models--Qwen--Qwen2.5-7B"
    blobs = model_dir / "blobs"
    blobs.mkdir(parents=True)
    # Fake weight blob — 12 MB sparse file. The completeness check requires at
    # least one snapshot entry ≥ 10 MB to treat the source as "real weights".
    blob_path = blobs / "sha256-abc123"
    with open(blob_path, "wb") as f:
        f.seek(12 * 1024 * 1024 - 1)
        f.write(b"\x00")
    refs = model_dir / "refs"
    refs.mkdir()
    (refs / "main").write_text("abc123")
    snapshots = model_dir / "snapshots" / "abc123"
    snapshots.mkdir(parents=True)
    # Symlink in snapshot pointing to blob
    (snapshots / "model.safetensors").symlink_to("../../blobs/sha256-abc123")

    return {
        "source_hf": str(source_hf),
        "tmpfs": str(tmpfs),
        "model_name": "Qwen/Qwen2.5-7B",
    }


@pytest.fixture
def manifest_only_source(tmp_path):
    """Source filesystem with a model directory containing only manifest files.

    Mirrors the xet-backed-not-yet-downloaded state that triggered the deioma
    ENOSPC crash: `models--*/` exists with config.json and *.index.json (small
    real files) but no weight blobs. RAM cache must refuse this and load from
    source HF_HOME so the weights download to disk, not tmpfs.
    """
    source_hf = tmp_path / "source" / "hub"
    source_hf.mkdir(parents=True)
    tmpfs = tmp_path / "ramcache"
    tmpfs.mkdir()

    model_dir = source_hf / "models--openai--gpt-oss-120b"
    (model_dir / "blobs").mkdir(parents=True)
    (model_dir / "refs").mkdir()
    (model_dir / "refs" / "main").write_text("a" * 40)
    rev = "b5c939de8f754692c1647ca79fbf85e8c1e70f8a"
    snap = model_dir / "snapshots" / rev
    snap.mkdir(parents=True)
    (snap / "config.json").write_bytes(b"x" * 2089)
    (snap / "model.safetensors.index.json").write_bytes(b"x" * 54511)

    return {
        "source_hf": str(source_hf),
        "tmpfs": str(tmpfs),
        "model_name": "openai/gpt-oss-120b",
    }


def test_model_size_bytes(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    size = cache.model_size_bytes(ram_cache_env["model_name"])
    # At minimum the 1KB blob + refs/main + symlink resolved
    assert size >= 1024


def test_model_size_bytes_unknown_model(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    assert cache.model_size_bytes("nonexistent/model") == 0


@pytest.mark.asyncio
async def test_ensure_cached_copies_model(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]

    # Mock _total_tmpfs_bytes so safety floor doesn't exceed available space
    cache._total_tmpfs_bytes = lambda: 0

    result = await cache.ensure_cached(model)
    # Should return the tmpfs-based HF_HOME
    cached_hub = os.path.join(ram_cache_env["tmpfs"], "hub")
    assert result == ram_cache_env["tmpfs"]

    # Model should now be in cached list
    assert model in cache.cached_models()

    # The model directory should exist in the cache
    cached_dir = os.path.join(cached_hub, "models--Qwen--Qwen2.5-7B")
    assert os.path.isdir(cached_dir)

    # The blob itself is a real file — it is the one copy of the weights.
    blob_path = os.path.join(cached_dir, "blobs", "sha256-abc123")
    assert os.path.isfile(blob_path)
    assert not os.path.islink(blob_path)

    # The snapshot entry stays a link into it. Materialising it here is what
    # made every cached model cost twice its size.
    snap_path = os.path.join(cached_dir, "snapshots", "abc123", "model.safetensors")
    assert os.path.islink(snap_path), "snapshot entry was dereferenced — the copy holds the weights twice"
    assert os.path.isfile(snap_path), "the relative link must resolve inside the copy"
    assert os.readlink(snap_path) == "../../blobs/sha256-abc123"


@pytest.mark.asyncio
async def test_cached_copy_is_not_larger_than_the_source(ram_cache_env):
    """The whole point of the cache is RAM, so a copy that inflates is a bug
    with no symptom other than the host running out. 12 MB of weights became
    24 MB; across six models that was ~170 GB of pure duplication."""
    from logos_worker_node.model_cache import _tree_size_bytes

    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    await cache.ensure_cached(ram_cache_env["model_name"])

    source = Path(ram_cache_env["source_hf"]) / "models--Qwen--Qwen2.5-7B"
    cached = Path(ram_cache_env["tmpfs"]) / "hub" / "models--Qwen--Qwen2.5-7B"

    assert _tree_size_bytes(cached) <= _tree_size_bytes(source)


def test_model_size_bytes_counts_the_weights_once(ram_cache_env):
    """It feeds the capacity check, and resolving the snapshot links made it
    report double — so the cache believed it needed twice the room it does."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    blob_bytes = 12 * 1024 * 1024

    size = cache.model_size_bytes(ram_cache_env["model_name"])

    assert blob_bytes <= size < 2 * blob_bytes


@pytest.mark.asyncio
async def test_a_dereferenced_copy_from_an_older_worker_is_rebuilt(ram_cache_env):
    """Copies already on the workers hold every weight twice. They load fine,
    so nothing else would ever notice — the staleness path has to, or the RAM
    is only reclaimed by hand."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    cached = Path(ram_cache_env["tmpfs"]) / "hub" / "models--Qwen--Qwen2.5-7B"

    # An old-style copy: the snapshot entry is a real file, not a link.
    await cache.ensure_cached(model)
    snap = cached / "snapshots" / "abc123" / "model.safetensors"
    snap.unlink()
    with open(snap, "wb") as f:
        f.seek(12 * 1024 * 1024 - 1)
        f.write(b"\x00")

    source = Path(ram_cache_env["source_hf"]) / "models--Qwen--Qwen2.5-7B"
    assert cache._is_stale(source, cached) is True

    await cache._copy_model(model)
    assert os.path.islink(snap), "the rebuild should have restored the link"


@pytest.mark.asyncio
async def test_ensure_cached_idempotent(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]

    cache._total_tmpfs_bytes = lambda: 0
    p1 = await cache.ensure_cached(model)
    p2 = await cache.ensure_cached(model)
    assert p1 == p2


@pytest.mark.asyncio
async def test_evict_removes_model(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]

    cache._total_tmpfs_bytes = lambda: 0
    await cache.ensure_cached(model)
    assert model in cache.cached_models()

    cache.evict(model)
    assert model not in cache.cached_models()


@pytest.mark.asyncio
async def test_cache_models_by_priority(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]

    cache._total_tmpfs_bytes = lambda: 0
    result = await cache.cache_models_by_priority([model, "nonexistent/model"])
    assert model in result
    # nonexistent model falls back to source
    assert "nonexistent/model" in result


def test_get_effective_hf_home_uncached(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    # Before caching, should return source dir parent
    result = cache.get_effective_hf_home("Qwen/Qwen2.5-7B")
    source_parent = os.path.dirname(ram_cache_env["source_hf"])
    assert result == source_parent


@pytest.mark.asyncio
async def test_scan_existing_on_init(ram_cache_env):
    """Verify that a cache created after a model was already cached detects it."""
    cache1 = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]
    cache1._total_tmpfs_bytes = lambda: 0
    await cache1.ensure_cached(model)

    # Create a second cache instance — should scan and find the model
    cache2 = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    assert model in cache2.cached_models()


@pytest.mark.asyncio
async def test_ensure_cached_skips_manifest_only_source(manifest_only_source):
    """A model whose source dir has only manifests (no weights) must not be cached.

    Regression test for the deioma ENOSPC crash: copying the manifest-only
    directory to tmpfs and pointing HF_HOME at tmpfs made vLLM download the
    full 60 GB weight set into the 100 GB tmpfs, overflowing it on the
    trailing refs/main write.
    """
    cache = ModelRamCache(
        tmpfs_path=manifest_only_source["tmpfs"],
        source_hf_hub_path=manifest_only_source["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0

    result = await cache.ensure_cached(manifest_only_source["model_name"])

    # Falls back to source HF_HOME (the parent of `hub/`) instead of tmpfs.
    source_parent = os.path.dirname(manifest_only_source["source_hf"])
    assert result == source_parent
    # Model is NOT marked cached.
    assert manifest_only_source["model_name"] not in cache.cached_models()
    # Tmpfs hub stays empty for this model.
    cached_dir = os.path.join(
        manifest_only_source["tmpfs"],
        "hub",
        "models--openai--gpt-oss-120b",
    )
    assert not os.path.exists(cached_dir)


def test_ensure_cached_sync_skips_manifest_only_source(manifest_only_source):
    """Sync variant (used by calibration) honors the same completeness check."""
    cache = ModelRamCache(
        tmpfs_path=manifest_only_source["tmpfs"],
        source_hf_hub_path=manifest_only_source["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0

    result = cache.ensure_cached_sync(manifest_only_source["model_name"])

    source_parent = os.path.dirname(manifest_only_source["source_hf"])
    assert result == source_parent
    assert manifest_only_source["model_name"] not in cache.cached_models()


def test_scan_existing_evicts_incomplete_cache(tmp_path):
    """A tmpfs entry with a 0-byte refs/<branch> (ENOSPC mid-download) is evicted.

    Without this, a worker that crashed once would loop forever: scan
    re-claims the broken directory as 'cached', ensure_cached returns the
    tmpfs HF_HOME, vLLM tries to use it, fails again on the same ref write.
    """

    source_hf = tmp_path / "source" / "hub"
    source_hf.mkdir(parents=True)
    tmpfs = tmp_path / "ramcache"
    tmpfs.mkdir()

    # Build a broken cached entry: blobs + snapshots present, refs/main empty.
    broken = tmpfs / "hub" / "models--openai--gpt-oss-120b"
    (broken / "blobs").mkdir(parents=True)
    (broken / "blobs" / "deadbeef").write_bytes(b"\x00" * 4096)
    (broken / "refs").mkdir()
    (broken / "refs" / "main").write_bytes(b"")  # 0-byte ref = ENOSPC marker
    (broken / "snapshots" / "rev1").mkdir(parents=True)

    cache = ModelRamCache(
        tmpfs_path=str(tmpfs),
        source_hf_hub_path=str(source_hf),
    )

    assert "openai/gpt-oss-120b" not in cache.cached_models()
    assert not broken.exists(), "incomplete tmpfs entry should have been evicted on scan"


def test_scan_existing_keeps_complete_cache(tmp_path):
    """A tmpfs entry with a non-empty refs/<branch> is retained."""
    source_hf = tmp_path / "source" / "hub"
    source_hf.mkdir(parents=True)
    tmpfs = tmp_path / "ramcache"
    tmpfs.mkdir()

    good = tmpfs / "hub" / "models--meta-llama--Llama-3.1-8B"
    (good / "blobs").mkdir(parents=True)
    (good / "refs").mkdir()
    (good / "refs" / "main").write_text("a" * 40)
    (good / "snapshots" / "rev1").mkdir(parents=True)

    cache = ModelRamCache(
        tmpfs_path=str(tmpfs),
        source_hf_hub_path=str(source_hf),
    )

    assert "meta-llama/Llama-3.1-8B" in cache.cached_models()
    assert good.exists()


# ─────────────────────────────────────────────────────────────────────────
# Background caching (start_background_caching / wait_for_cached)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_background_caching_does_not_block_startup(ram_cache_env):
    """Startup must return immediately even when the queue has work to do.
    Previously cache_models_by_priority blocked the lifespan hook for
    multi-minute rsync sweeps; the new entry point spins up a task and
    returns synchronously."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]

    cache.start_background_caching([model])
    # The worker task should be running but caching may not have completed yet.
    assert cache._caching_task is not None
    # Drain it for cleanup.
    await cache.wait_for_cached(model)
    assert cache.is_cached(model)
    await cache.stop_background_caching()


@pytest.mark.asyncio
async def test_wait_for_cached_returns_immediately_when_already_cached(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]

    await cache.ensure_cached(model)
    assert cache.is_cached(model)
    # wait_for_cached on an already-cached model should be a no-op (and fast)
    import asyncio as _asyncio

    got = await _asyncio.wait_for(cache.wait_for_cached(model), timeout=1.0)
    assert got is True


@pytest.mark.asyncio
async def test_wait_for_cached_bumps_priority_when_queued_behind_others(ram_cache_env, tmp_path):
    """A lane add for a queued-but-not-yet-cached model should bump it to
    the front of the queue so the lane doesn't wait behind models it
    doesn't need."""
    # Build a second model on the source so we can enqueue two and bump one.
    source_hf = tmp_path / "source" / "hub"
    other_dir = source_hf / "models--Qwen--Other"
    other_blobs = other_dir / "blobs"
    other_blobs.mkdir(parents=True)
    with open(other_blobs / "sha256-other", "wb") as f:
        f.seek(12 * 1024 * 1024 - 1)
        f.write(b"\x00")
    (other_dir / "refs").mkdir()
    (other_dir / "refs" / "main").write_text("other")
    snap = other_dir / "snapshots" / "other"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").symlink_to("../../blobs/sha256-other")

    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0

    # Stop the worker before it does anything so we can inspect the queue.
    cache._cache_queue_event = __import__("asyncio").Event()
    cache._enqueue("Qwen/Qwen2.5-7B", priority=False)
    cache._enqueue("Qwen/Other", priority=False)
    assert list(cache._cache_queue) == ["Qwen/Qwen2.5-7B", "Qwen/Other"]

    # A lane add for the second model bumps it to the front.
    cache._enqueue("Qwen/Other", priority=True)
    assert list(cache._cache_queue) == ["Qwen/Other", "Qwen/Qwen2.5-7B"]


@pytest.mark.asyncio
async def test_stop_background_caching_cancels_worker(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    # Empty queue → worker will park on the event.
    cache.start_background_caching([])
    task = cache._caching_task
    assert task is not None and not task.done()
    await cache.stop_background_caching()
    assert task.done()


@pytest.mark.asyncio
async def test_wait_for_cached_starts_worker_when_none_running(ram_cache_env):
    """A lane request that arrives before start_background_caching was
    ever called (e.g. ad-hoc lane add for a model not in the plan) must
    still trigger caching."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    assert cache._caching_task is None

    got = await cache.wait_for_cached(ram_cache_env["model_name"])
    assert got is True
    assert cache.is_cached(ram_cache_env["model_name"])
    await cache.stop_background_caching()


@pytest.mark.asyncio
async def test_wait_for_cached_respects_timeout(ram_cache_env, monkeypatch):
    """When the rsync takes longer than the timeout, wait_for_cached
    returns False so the caller can fall back to loading from disk."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0

    # Make the underlying ensure_cached block forever so timeout triggers.
    import asyncio as _asyncio

    async def _hang(_model_name: str) -> str:
        await _asyncio.sleep(60)
        return ""

    monkeypatch.setattr(cache, "ensure_cached", _hang)

    got = await cache.wait_for_cached(ram_cache_env["model_name"], timeout=0.1)
    assert got is False
    await cache.stop_background_caching()


# ---------------------------------------------------------------------------
# The cache yields host RAM back
#
# tmpfs pages are anonymous shared memory, so a cached model is RAM the host
# cannot use for anything else — and unlike page cache it is never reclaimed
# under pressure. sleep_l1 wants the same RAM for a lane's weights. Until
# these existed the cache filled to its tmpfs limit on first boot and kept
# every byte, whatever the lanes needed later.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_held_bytes_reports_what_the_cache_costs_the_host(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    assert cache.held_bytes() == 0

    await cache.ensure_cached(ram_cache_env["model_name"])

    assert cache.held_bytes() >= 12 * 1024 * 1024


@pytest.mark.asyncio
async def test_reclaim_drops_what_the_plan_no_longer_wants(ram_cache_env):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    await cache.ensure_cached(model)
    assert model in cache.cached_models()

    removed = await cache.reclaim(keep=set())

    assert removed == [model]
    assert cache.cached_models() == []
    assert cache.held_bytes() == 0
    assert not (Path(ram_cache_env["tmpfs"]) / "hub" / "models--Qwen--Qwen2.5-7B").exists()


@pytest.mark.asyncio
async def test_reclaim_keeps_what_it_is_told_to(ram_cache_env):
    """Callers pass the models a lane is serving: a lane waking from sleep_l2
    re-reads its weights from the HF_HOME it was started with, so pulling that
    directory away turns a wake into a failed lane."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    await cache.ensure_cached(model)

    assert await cache.reclaim(keep={model}) == []
    assert model in cache.cached_models()


@pytest.mark.asyncio
async def test_reclaim_coordinates_with_the_copy_worker(ram_cache_env) -> None:
    """reclaim now runs on a 60 s tick next to in-flight copies: a copy in
    flight is left alone (the worker owns its tree — a concurrent rmtree
    would tear it), and queue entries the plan rejected are dropped, with
    their completion events released, so the worker does not copy a model
    the plan just threw away and a waiting lane falls back to disk
    immediately instead of waiting out its timeout."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    await cache.ensure_cached(model)

    # A second model is queued for a copy that has not started yet; the
    # plan no longer wants it.
    queued = "org/not-in-the-plan"
    event = cache._enqueue(queued, priority=False)  # noqa: SLF001
    assert queued in cache._cache_queue  # noqa: SLF001

    removed = await cache.reclaim(keep={model})

    assert removed == []  # the kept model survives, the queued one was not cached
    assert queued not in cache._cache_queue  # noqa: SLF001
    assert event.is_set()  # the waiter is released and falls back to disk
    assert cache.is_cached(queued) is False

    # A copy in flight (model marked _caching_now) is spared this pass.
    cache._caching_now = model  # noqa: SLF001
    assert await cache.reclaim(keep=set()) == []
    assert model in cache.cached_models()


@pytest.mark.asyncio
async def test_the_cache_refuses_to_grow_into_the_sleep_reserve(ram_cache_env, monkeypatch):
    """The tmpfs mount is a fixed 400G of a 503G host, so tmpfs free space is
    no bound at all. What bounds the cache is live host RAM against the RAM
    reserved for sleeping lanes — which is why a lane putting weights in host
    RAM shrinks the cache's room with nobody re-planning anything."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        # 1 MB of slack for a 12 MB model: tmpfs has plenty of room, the host
        # does not.
        lambda: 100_001 * 1024 * 1024,
    )

    result = await cache.ensure_cached(ram_cache_env["model_name"])

    assert result == str(Path(ram_cache_env["source_hf"]).parent), "should load from the source HF_HOME"
    assert ram_cache_env["model_name"] not in cache.cached_models()


@pytest.mark.asyncio
async def test_a_roomy_host_still_gets_the_cache(ram_cache_env, monkeypatch):
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        lambda: 400_000 * 1024 * 1024,
    )

    await cache.ensure_cached(ram_cache_env["model_name"])

    assert ram_cache_env["model_name"] in cache.cached_models()


def test_no_floor_configured_leaves_the_decision_to_tmpfs(ram_cache_env, monkeypatch):
    """Fails open: a worker with no plan yet, or no /proc/meminfo, behaves
    exactly as it did before the floor existed."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    monkeypatch.setattr("logos_worker_node.model_cache._host_ram_available_bytes", lambda: None)

    cache.set_host_ram_floor_mb(100_000.0)
    assert cache._would_starve_host(1) == (False, 0)

    cache.set_host_ram_floor_mb(0.0)
    assert cache._would_starve_host(10**15) == (False, 0)


# ---------------------------------------------------------------------------
# The floor is re-checked for entries that are ALREADY in the cache
#
# The copy path checks the host-RAM floor before admitting NEW bytes, but an
# entry that is already resident in tmpfs is handed out without a copy, so the
# floor was never re-checked for it. That leaves two windows where a lane can
# be launched from an entry the current sleep reserve no longer fits: one
# cached under an earlier, smaller floor (e.g. a startup pre-population), and
# one whose in-flight copy was admitted under that older floor and has since
# finished. Both land on the same already-cached branch of ensure_cached.
# ---------------------------------------------------------------------------


def _prime_cached_entry(cache, model: str, monkeypatch) -> None:
    """Copy *model* into the cache under a floor of 0 (as a startup
    pre-population would), so the tests can then raise the floor and re-check
    the already-resident entry."""
    cache.set_host_ram_floor_mb(0.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        lambda: 400_000 * 1024 * 1024,
    )
    assert cache.ensure_cached_sync(model) == str(cache._cache_hub.parent)
    assert model in cache.cached_models()


@pytest.mark.asyncio
async def test_already_cached_entry_is_served_from_disk_when_the_floor_rises_past_it(ram_cache_env, monkeypatch):
    """Regression: an entry already in tmpfs is now re-checked against the live
    floor before it is handed to a lane. Once the re-plan has raised the sleep
    reserve past it (the host is already below the floor with the entry in
    place), the lane loads from the source HF_HOME instead of the tmpfs entry —
    serving it from the entry would protect the entry (the lane reads it) and
    leave the lane's first sleep short of planned host RAM."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _prime_cached_entry(cache, model, monkeypatch)

    # The re-plan has since raised the sleep reserve; the host is now under it
    # with the (12 MB) entry resident.
    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr("logos_worker_node.model_cache._host_ram_available_bytes", lambda: 50 * 1024 * 1024)

    result = await cache.ensure_cached(model)

    # Served from the source HF_HOME, not the over-floor tmpfs entry.
    assert result == str(Path(ram_cache_env["source_hf"]).parent)
    # Nothing evicted the entry — it is still in the cache, and is now
    # evictable because the lane did not launch from it.
    assert model in cache.cached_models()


@pytest.mark.asyncio
async def test_already_cached_entry_served_from_cache_when_host_above_floor(ram_cache_env, monkeypatch):
    """The re-check must not over-reject: it gates on the host being BELOW the
    floor, not on the entry's size. A host at or above the floor still serves
    the already-cached model from the tmpfs cache."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _prime_cached_entry(cache, model, monkeypatch)

    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        lambda: 150_000 * 1024 * 1024,
    )

    assert await cache.ensure_cached(model) == str(Path(ram_cache_env["tmpfs"]))


@pytest.mark.asyncio
async def test_already_cached_entry_floor_check_fails_open_without_meminfo(ram_cache_env, monkeypatch):
    """Like the copy path, the already-cached re-check fails open: a set floor
    with no /proc/meminfo read leaves the entry to be served from the cache,
    exactly as before the floor existed."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _prime_cached_entry(cache, model, monkeypatch)

    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr("logos_worker_node.model_cache._host_ram_available_bytes", lambda: None)

    assert await cache.ensure_cached(model) == str(Path(ram_cache_env["tmpfs"]))


def test_ensure_cached_sync_rechecks_the_floor_for_an_already_cached_entry(ram_cache_env, monkeypatch):
    """The sync path (used by calibration) applies the same re-check to an
    already-resident entry."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _prime_cached_entry(cache, model, monkeypatch)

    cache.set_host_ram_floor_mb(100_000.0)
    monkeypatch.setattr("logos_worker_node.model_cache._host_ram_available_bytes", lambda: 50 * 1024 * 1024)

    assert cache.ensure_cached_sync(model) == str(Path(ram_cache_env["source_hf"]).parent)
    assert model in cache.cached_models()


# ---------------------------------------------------------------------------
# The floor is re-checked when the copy COMPLETES in the same call
#
# The pre-copy check is a snapshot: the re-plan runs on a tick and after
# every lane sleep, so the sleep reserve can rise while a multi-minute rsync
# is running. The copy then lands under the raised reserve, and the call
# that admitted it must not hand the over-floor entry to the lane — serving
# it from the entry would protect the entry (the lane reads it) and leave
# the lane's first sleep short of planned host RAM.
# ---------------------------------------------------------------------------


def _copy_with_floor_raised_midway(cache, monkeypatch, available_after: int) -> None:
    """Wrap the copy so the re-plan raises the sleep reserve while it runs:
    the pre-copy check sees a roomy host under a zero floor, the copy starts,
    the floor jumps to 100 GB, and the copy finishes."""
    cache.set_host_ram_floor_mb(0.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        lambda: 400_000 * 1024 * 1024,
    )
    original_copy = cache._copy_model

    async def copy_then_raise_floor(model_name: str) -> bool:
        cache.set_host_ram_floor_mb(100_000.0)
        monkeypatch.setattr(
            "logos_worker_node.model_cache._host_ram_available_bytes", lambda: available_after
        )
        return await original_copy(model_name)

    monkeypatch.setattr(cache, "_copy_model", copy_then_raise_floor)


def _copy_sync_with_floor_raised_midway(cache, monkeypatch, available_after: int) -> None:
    """Sync counterpart of _copy_with_floor_raised_midway (calibration path)."""
    cache.set_host_ram_floor_mb(0.0)
    monkeypatch.setattr(
        "logos_worker_node.model_cache._host_ram_available_bytes",
        lambda: 400_000 * 1024 * 1024,
    )
    original_copy = cache._copy_model_sync

    def copy_sync_then_raise_floor(model_name: str) -> bool:
        cache.set_host_ram_floor_mb(100_000.0)
        monkeypatch.setattr(
            "logos_worker_node.model_cache._host_ram_available_bytes", lambda: available_after
        )
        return original_copy(model_name)

    monkeypatch.setattr(cache, "_copy_model_sync", copy_sync_then_raise_floor)


@pytest.mark.asyncio
async def test_floor_raised_during_the_copy_is_served_from_disk(ram_cache_env, monkeypatch):
    """Regression: the pre-copy floor check is a snapshot, and the re-plan
    can raise the sleep reserve while the copy runs. Once the copy completes
    under the raised reserve (the host is below the floor with the entry in
    place), the lane loads from the source HF_HOME instead of the tmpfs entry
    — serving it from the entry would protect it and leave the lane's first
    sleep short of planned host RAM. The entry stays in the cache, evictable
    because the lane did not launch from it."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _copy_with_floor_raised_midway(cache, monkeypatch, available_after=50 * 1024 * 1024)

    result = await cache.ensure_cached(model)

    assert result == str(Path(ram_cache_env["source_hf"]).parent)
    assert model in cache.cached_models()


@pytest.mark.asyncio
async def test_copy_completed_under_a_reserve_the_host_still_clears_serves_the_cache(ram_cache_env, monkeypatch):
    """The post-copy re-check must not over-reject: it gates on the host
    being BELOW the floor with the entry resident, not on the floor having
    changed at all. A raised reserve the host still clears serves the cache."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _copy_with_floor_raised_midway(cache, monkeypatch, available_after=150_000 * 1024 * 1024)

    result = await cache.ensure_cached(model)

    assert result == str(Path(ram_cache_env["tmpfs"]))
    assert model in cache.cached_models()


def test_ensure_cached_sync_rechecks_the_floor_after_its_own_copy(ram_cache_env, monkeypatch):
    """The sync path (used by calibration) applies the same re-check when the
    reserve rises while its copy runs."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    cache._total_tmpfs_bytes = lambda: 0
    model = ram_cache_env["model_name"]
    _copy_sync_with_floor_raised_midway(cache, monkeypatch, available_after=50 * 1024 * 1024)

    result = cache.ensure_cached_sync(model)

    assert result == str(Path(ram_cache_env["source_hf"]).parent)
    assert model in cache.cached_models()


def test_cache_use_reservation_is_reference_counted(ram_cache_env):
    """The re-plan protects the entries of lanes that read the cache, but
    calibration reads its entry with no lane handle behind it — the reservation
    is what pins the tree for the whole calibration session. Reference counting
    keeps an overlapping use (a re-run of the session) from un-reserving the
    other, and a stray release must not corrupt the count."""
    cache = ModelRamCache(
        tmpfs_path=ram_cache_env["tmpfs"],
        source_hf_hub_path=ram_cache_env["source_hf"],
    )
    model = ram_cache_env["model_name"]

    assert cache.cache_use_reservations() == set()
    cache.reserve_cache_use(model)
    assert cache.cache_use_reservations() == {model}
    # Overlapping uses: the first release keeps the entry reserved.
    cache.reserve_cache_use(model)
    cache.release_cache_use(model)
    assert cache.cache_use_reservations() == {model}
    cache.release_cache_use(model)
    assert cache.cache_use_reservations() == set()
    # A release with no matching reservation is a no-op, not an error.
    cache.release_cache_use(model)
    assert cache.cache_use_reservations() == set()


def test_disabled_cache_treats_cache_use_reservations_as_noop():
    """The stand-in the worker uses when tmpfs caching is off must accept the
    same reserve/release calls (calibration does not special-case it)."""
    cache = create_model_cache(tmpfs_path=None, hf_home="/unused")

    assert cache.cache_use_reservations() == set()
    cache.reserve_cache_use("org/m")
    cache.release_cache_use("org/m")
    cache.release_cache_use("org/m")
    assert cache.cache_use_reservations() == set()
