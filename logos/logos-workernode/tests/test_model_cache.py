"""Tests for the ModelRamCache (Feature 3: tmpfs RAM cache)."""

from __future__ import annotations

import os

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

    # Blob should be a regular file (rsync -aL dereferences symlinks)
    blob_path = os.path.join(cached_dir, "blobs", "sha256-abc123")
    assert os.path.isfile(blob_path)


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
