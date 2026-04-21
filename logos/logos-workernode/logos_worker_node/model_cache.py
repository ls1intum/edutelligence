"""tmpfs-backed RAM cache for HuggingFace model files.

When LOGOS_TMPFS_CACHE_PATH is set to a tmpfs mount (e.g. /mnt/ramcache),
this module copies model directories from the source HF cache into the
tmpfs for faster loading.  Only models in ``capabilities_models`` are cached.

The cache copies entire ``models--org--name/`` directories using
``rsync -aL`` (dereference symlinks) to produce a self-contained copy.
Partial copies use a ``.partial`` suffix and are renamed atomically on
completion to avoid serving incomplete data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFETY_MARGIN_RATIO = 0.10  # keep ≥10% tmpfs free


def _hf_model_dir_name(model_name: str) -> str:
    """Convert ``org/name`` to ``models--org--name`` (HF cache convention)."""
    return "models--" + model_name.replace("/", "--")


def _is_tmpfs(path: str) -> bool:
    """Check if *path* is a tmpfs mount (Linux only, best-effort)."""
    proc_mounts = Path("/proc/mounts")
    if not proc_mounts.exists():
        return os.path.ismount(path)
    try:
        resolved = os.path.realpath(path)
        for line in proc_mounts.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == resolved and parts[2] == "tmpfs":
                return True
    except OSError:
        pass
    return os.path.ismount(path)


class ModelRamCache:
    """Manages a tmpfs-backed RAM cache for model files."""

    def __init__(
        self,
        tmpfs_path: str,
        source_hf_hub_path: str,
        max_size_bytes: int = 0,
    ) -> None:
        """
        Parameters
        ----------
        tmpfs_path:
            Mount point (e.g. ``/mnt/ramcache``).  A ``hub/`` subdirectory
            will be created underneath to mirror the HF cache layout.
        source_hf_hub_path:
            Original HF hub cache directory, e.g.
            ``/usr/share/ollama/.ollama/models/.hf_cache/hub``.
        max_size_bytes:
            Hard cap.  0 = auto-detect from tmpfs available space.
        """
        self._tmpfs_root = Path(tmpfs_path)
        self._cache_hub = self._tmpfs_root / "hub"
        self._source_hub = Path(source_hf_hub_path)
        self._max_size_bytes = max_size_bytes
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._cached_models: set[str] = set()

        self._cache_hub.mkdir(parents=True, exist_ok=True)
        self._scan_existing()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def available_space_bytes(self) -> int:
        """Query actual free space on the tmpfs mount."""
        try:
            st = os.statvfs(str(self._tmpfs_root))
            return st.f_bavail * st.f_frsize
        except OSError:
            return 0

    def cached_models(self) -> list[str]:
        """List models currently in the cache."""
        return sorted(self._cached_models)

    def model_size_bytes(self, model_name: str) -> int:
        """Get total size of model on the source filesystem."""
        src = self._source_hub / _hf_model_dir_name(model_name)
        if not src.exists():
            return 0
        total = 0
        for root, _dirs, files in os.walk(src, followlinks=True):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    async def ensure_cached(self, model_name: str) -> str:
        """Copy model into tmpfs if not already cached and space permits.

        Returns the path to use for loading (tmpfs path if cached, source
        path if not).  Uses ``rsync -aL`` (dereferences symlinks).
        """
        lock = await self._get_model_lock(model_name)
        async with lock:
            if model_name in self._cached_models:
                cached = self._cache_hub / _hf_model_dir_name(model_name)
                if cached.exists():
                    logger.info("Model %s: loading from tmpfs RAM cache", model_name)
                    return str(self._cache_hub.parent)
                self._cached_models.discard(model_name)

            size = await asyncio.to_thread(self.model_size_bytes, model_name)
            if size <= 0:
                logger.warning("Model %s not found on source filesystem — loading from disk", model_name)
                return str(self._source_hub.parent)

            available = self.available_space_bytes()
            total_fs = self._total_tmpfs_bytes()
            safety_floor = int(total_fs * _SAFETY_MARGIN_RATIO) if total_fs > 0 else 0

            if available - size < safety_floor:
                logger.warning(
                    "Skipping RAM cache for %s: need %d MB, available %d MB "
                    "(safety floor %d MB) — loading from disk",
                    model_name, size // (1024 * 1024),
                    available // (1024 * 1024), safety_floor // (1024 * 1024),
                )
                return str(self._source_hub.parent)

            ok = await self._copy_model(model_name)
            if ok:
                self._cached_models.add(model_name)
                logger.info("Model %s: loading from tmpfs RAM cache", model_name)
                return str(self._cache_hub.parent)
            logger.warning("Model %s: copy to RAM cache failed — loading from disk", model_name)
            return str(self._source_hub.parent)

    def ensure_cached_sync(self, model_name: str) -> str:
        """Synchronous version of ensure_cached for use from threads (e.g. calibration).

        Returns the HF_HOME path to use: tmpfs cache path if successfully cached,
        source path if not (space exhausted, model not found, or copy failed).
        """
        if model_name in self._cached_models:
            cached = self._cache_hub / _hf_model_dir_name(model_name)
            if cached.exists():
                logger.info("Model %s: already in tmpfs RAM cache", model_name)
                return str(self._cache_hub.parent)
            self._cached_models.discard(model_name)

        size = self.model_size_bytes(model_name)
        if size <= 0:
            logger.warning("Model %s not found on source filesystem — loading from disk", model_name)
            return str(self._source_hub.parent)

        available = self.available_space_bytes()
        total_fs = self._total_tmpfs_bytes()
        safety_floor = int(total_fs * _SAFETY_MARGIN_RATIO) if total_fs > 0 else 0

        if available - size < safety_floor:
            logger.warning(
                "Skipping RAM cache for %s: need %d MB, available %d MB "
                "(safety floor %d MB) — loading from disk",
                model_name, size // (1024 * 1024),
                available // (1024 * 1024), safety_floor // (1024 * 1024),
            )
            return str(self._source_hub.parent)

        ok = self._copy_model_sync(model_name)
        if ok:
            self._cached_models.add(model_name)
            logger.info("Model %s: cached to tmpfs RAM cache (sync)", model_name)
            return str(self._cache_hub.parent)
        logger.warning("Model %s: copy to RAM cache failed — loading from disk", model_name)
        return str(self._source_hub.parent)

    def _copy_model_sync(self, model_name: str) -> bool:
        """Synchronous (blocking) copy of model into tmpfs using subprocess rsync."""
        dir_name = _hf_model_dir_name(model_name)
        src = self._source_hub / dir_name
        target = self._cache_hub / dir_name
        partial = self._cache_hub / (dir_name + ".partial")

        if not src.exists():
            logger.error("Source model dir does not exist: %s", src)
            return False

        if target.exists():
            if self._is_stale(src, target):
                logger.info("Evicting stale cached copy of %s", model_name)
                shutil.rmtree(target, ignore_errors=True)
            else:
                return True

        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)

        size_mb = self.model_size_bytes(model_name) / (1024 * 1024)
        t0 = time.monotonic()
        logger.info(
            "Copying %s into RAM cache (%.0f MB, %s -> %s)",
            model_name, size_mb, src, partial,
        )

        try:
            rsync_available = shutil.which("rsync") is not None
            if rsync_available:
                proc = subprocess.Popen(  # noqa: S603
                    ["rsync", "-aL", "--delete", "--info=progress2", "--no-inc-recursive",
                     str(src) + "/", str(partial) + "/"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                _last_log = time.monotonic()
                _LOG_INTERVAL = 30.0  # log progress every 30s
                for line in proc.stdout or []:
                    line = line.strip()
                    if not line:
                        continue
                    now = time.monotonic()
                    if now - _last_log >= _LOG_INTERVAL:
                        # rsync --info=progress2 emits lines like:
                        #   1,234,567,890  42%  123.45MB/s  0:01:23
                        logger.info("  [RAM cache] %s — %s", model_name, line)
                        _last_log = now
                proc.wait()
                if proc.returncode != 0:
                    logger.error(
                        "rsync failed for %s (rc=%d)",
                        model_name, proc.returncode,
                    )
                    shutil.rmtree(partial, ignore_errors=True)
                    return False
            else:
                shutil.copytree(str(src), str(partial), symlinks=False, dirs_exist_ok=True)
        except Exception:
            logger.exception("Failed to copy %s into RAM cache", model_name)
            shutil.rmtree(partial, ignore_errors=True)
            return False

        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            partial.rename(target)
        except OSError:
            logger.exception("Failed to rename partial copy for %s", model_name)
            shutil.rmtree(partial, ignore_errors=True)
            return False

        elapsed = time.monotonic() - t0
        logger.info(
            "Cached %s in RAM (%.0f MB in %.1fs, %.0f MB/s) [sync]",
            model_name, size_mb, elapsed,
            size_mb / elapsed if elapsed > 0 else 0,
        )
        return True

    async def cache_models_by_priority(self, models: list[str]) -> dict[str, str]:
        """Cache models in priority order (first = highest priority).

        Stops when tmpfs is full.  Returns ``model_name -> effective_hf_home``
        mapping.
        """
        result: dict[str, str] = {}
        for model_name in models:
            effective = await self.ensure_cached(model_name)
            result[model_name] = effective
        return result

    def evict(self, model_name: str) -> None:
        """Remove a model from the cache to free space."""
        target = self._cache_hub / _hf_model_dir_name(model_name)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            logger.info("Evicted %s from RAM cache", model_name)
        self._cached_models.discard(model_name)

    def get_effective_hf_home(self, model_name: str) -> str:
        """Return tmpfs-based HF_HOME if cached, else source HF_HOME."""
        if model_name in self._cached_models:
            cached = self._cache_hub / _hf_model_dir_name(model_name)
            if cached.exists():
                logger.debug("Model %s: using tmpfs RAM cache path", model_name)
                return str(self._cache_hub.parent)
        logger.debug("Model %s: using source filesystem path", model_name)
        return str(self._source_hub.parent)

    @property
    def enabled(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _total_tmpfs_bytes(self) -> int:
        try:
            st = os.statvfs(str(self._tmpfs_root))
            return st.f_blocks * st.f_frsize
        except OSError:
            return 0

    def _scan_existing(self) -> None:
        """Detect models already present in tmpfs from a previous run."""
        if not self._cache_hub.exists():
            return
        for entry in self._cache_hub.iterdir():
            if entry.is_dir() and entry.name.startswith("models--"):
                parts = entry.name.split("--", 1)
                if len(parts) >= 2:
                    model_name = parts[1].replace("--", "/")
                    self._cached_models.add(model_name)
                    logger.info("Found existing cached model: %s", model_name)

    async def _get_model_lock(self, model_name: str) -> asyncio.Lock:
        async with self._global_lock:
            if model_name not in self._locks:
                self._locks[model_name] = asyncio.Lock()
            return self._locks[model_name]

    async def _copy_model(self, model_name: str) -> bool:
        """Copy model directory into tmpfs using rsync.

        Uses a ``.partial`` suffix during copy and renames atomically on
        completion.
        """
        dir_name = _hf_model_dir_name(model_name)
        src = self._source_hub / dir_name
        target = self._cache_hub / dir_name
        partial = self._cache_hub / (dir_name + ".partial")

        if not src.exists():
            logger.error("Source model dir does not exist: %s", src)
            return False

        # Check for stale partials (cache invalidation)
        if target.exists():
            if self._is_stale(src, target):
                logger.info("Evicting stale cached copy of %s", model_name)
                shutil.rmtree(target, ignore_errors=True)
            else:
                return True

        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)

        size_mb = self.model_size_bytes(model_name) / (1024 * 1024)
        t0 = time.monotonic()
        logger.info(
            "Copying %s into RAM cache (%.0f MB, %s -> %s)",
            model_name, size_mb, src, partial,
        )

        try:
            rsync_available = shutil.which("rsync") is not None
            if rsync_available:
                proc = await asyncio.create_subprocess_exec(
                    "rsync", "-aL", "--delete",
                    str(src) + "/", str(partial) + "/",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.error(
                        "rsync failed for %s (rc=%d): %s",
                        model_name, proc.returncode,
                        stderr.decode(errors="replace")[:500],
                    )
                    shutil.rmtree(partial, ignore_errors=True)
                    return False
            else:
                await asyncio.to_thread(
                    shutil.copytree, str(src), str(partial),
                    symlinks=False, dirs_exist_ok=True,
                )
        except Exception:
            logger.exception("Failed to copy %s into RAM cache", model_name)
            shutil.rmtree(partial, ignore_errors=True)
            return False

        # Atomic rename
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            partial.rename(target)
        except OSError:
            logger.exception("Failed to rename partial copy for %s", model_name)
            shutil.rmtree(partial, ignore_errors=True)
            return False

        elapsed = time.monotonic() - t0
        size_mb = self.model_size_bytes(model_name) / (1024 * 1024)
        logger.info(
            "Cached %s in RAM (%.0f MB in %.1fs, %.0f MB/s)",
            model_name, size_mb, elapsed,
            size_mb / elapsed if elapsed > 0 else 0,
        )
        return True

    def _is_stale(self, src: Path, cached: Path) -> bool:
        """Check if source is newer than cached copy by comparing mtimes."""
        try:
            src_mtime = self._newest_mtime(src)
            cached_mtime = self._newest_mtime(cached)
            return src_mtime > cached_mtime
        except OSError:
            return True

    @staticmethod
    def _newest_mtime(directory: Path) -> float:
        """Find the newest mtime in a directory tree."""
        newest = 0.0
        for root, _dirs, files in os.walk(directory, followlinks=True):
            for f in files:
                try:
                    mt = os.path.getmtime(os.path.join(root, f))
                    if mt > newest:
                        newest = mt
                except OSError:
                    pass
        return newest


class _DisabledModelRamCache:
    """No-op stand-in when tmpfs caching is disabled."""

    @property
    def enabled(self) -> bool:
        return False

    def cached_models(self) -> list[str]:
        return []

    def available_space_bytes(self) -> int:
        return 0

    async def ensure_cached(self, model_name: str) -> str:  # noqa: ARG002
        return ""

    def ensure_cached_sync(self, model_name: str) -> str:  # noqa: ARG002
        return ""

    async def cache_models_by_priority(self, models: list[str]) -> dict[str, str]:
        return {}

    def evict(self, model_name: str) -> None:  # noqa: ARG002
        pass

    def get_effective_hf_home(self, model_name: str) -> str:  # noqa: ARG002
        return ""


def create_model_cache(
    tmpfs_path: str | None,
    hf_home: str,
) -> ModelRamCache | _DisabledModelRamCache:
    """Factory: return a real cache if tmpfs_path is configured, else a no-op.

    Parameters
    ----------
    tmpfs_path:
        Value of ``LOGOS_TMPFS_CACHE_PATH`` env var.  Empty or None = disabled.
    hf_home:
        Value of ``HF_HOME`` env var (e.g. ``/usr/share/ollama/.ollama/models/.hf_cache``).
    """
    if not tmpfs_path:
        return _DisabledModelRamCache()

    if not os.path.isdir(tmpfs_path):
        logger.warning(
            "LOGOS_TMPFS_CACHE_PATH=%s does not exist or is not a directory — RAM cache disabled",
            tmpfs_path,
        )
        return _DisabledModelRamCache()

    if not _is_tmpfs(tmpfs_path) and not os.path.ismount(tmpfs_path):
        logger.warning(
            "LOGOS_TMPFS_CACHE_PATH=%s is not a tmpfs or mount point — using anyway (may consume disk instead of RAM)",
            tmpfs_path,
        )

    source_hub = os.path.join(hf_home, "hub")
    if not os.path.isdir(source_hub):
        logger.warning(
            "HF hub cache directory not found at %s — RAM cache disabled",
            source_hub,
        )
        return _DisabledModelRamCache()

    cache = ModelRamCache(
        tmpfs_path=tmpfs_path,
        source_hf_hub_path=source_hub,
    )
    total_mb = cache._total_tmpfs_bytes() / (1024 * 1024)
    avail_mb = cache.available_space_bytes() / (1024 * 1024)
    is_ram = _is_tmpfs(tmpfs_path)
    logger.info(
        "RAM cache enabled: %s (%s) — %.0f MB total, %.0f MB available, source_hub=%s",
        tmpfs_path,
        "tmpfs (RAM)" if is_ram else "disk mount — NOT RAM!",
        total_mb, avail_mb, source_hub,
    )
    if cache.cached_models():
        logger.info(
            "  Pre-existing cached model(s) found in tmpfs: %s",
            cache.cached_models(),
        )
    return cache
