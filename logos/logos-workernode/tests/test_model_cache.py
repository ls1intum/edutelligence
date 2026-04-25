"""Tests for the ModelRamCache (Feature 3: tmpfs RAM cache)."""

from __future__ import annotations

import os
import asyncio

import pytest

from logos_worker_node.model_cache import (
    ModelRamCache,
    _DisabledModelRamCache,
    _hf_model_dir_name,
    create_model_cache,
)


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
    # Create a fake weight file (1KB)
    (blobs / "sha256-abc123").write_bytes(b"\x00" * 1024)
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
