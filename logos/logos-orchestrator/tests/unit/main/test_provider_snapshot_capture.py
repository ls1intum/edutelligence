"""A VRAM snapshot that fails to persist must not drop the worker.

``_capture_logosnode_provider_snapshot`` is awaited inside the worker
WebSocket ``status`` handler. If it raised, the exception would propagate out
of that handler and the session would be detached — for every worker. That is
the failure mode of starting the orchestrator before the webservice migration
that (re)creates ``provider_snapshots`` has run, or any transient database
error. The capture is telemetry, so a persistence failure is logged and the
sample is skipped; the worker stays connected and the next status message
retries.

The database write runs in a per-provider background writer so the receive
loop (which also relays stream chunks) never waits on it.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

import logos as main_mod
from logos.routers import logosnode as logosnode_mod

_TS = "2026-09-03T12:00:00+00:00"


class _SnapshotDB:
    """Stand-in for ``DBManager`` whose snapshot insert can raise."""

    def __init__(self, *, raises: Exception | None = None, snapshot_id: int = 123):
        self._raises = raises
        self._snapshot_id = snapshot_id
        self.inserts: list[dict] = []
        self.thread: int | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def inserted(self) -> dict | None:
        return self.inserts[-1] if self.inserts else None

    def insert_provider_snapshot(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        self.inserts.append(kwargs)
        self.thread = threading.get_ident()
        return self._snapshot_id


class _Registry:
    def __init__(self):
        self.samples: list[dict] = []

    async def record_runtime_sample(self, provider_id, sample):
        self.samples.append(sample)


def _sample(runtime: dict) -> dict:
    return {
        "timestamp": runtime.get("timestamp"),
        "used_vram_mb": 2048.0,
        "total_vram_mb": 49152,
        "remaining_vram_mb": 47104.0,
        "models_loaded": 1,
        "loaded_models": [{"name": "Qwen/Qwen3-8B", "size_vram_mb": 2048}],
        "snapshot_source": "logosnode-runtime",
        "runtime_payload": runtime,
        "scheduler_signals": {},
    }


@pytest.fixture
def registry(monkeypatch):
    registry = _Registry()
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    for name in ("_unsaved_samples", "_sample_writers", "_last_runtime_ts", "_last_snapshot_at", "_resync_rounds"):
        monkeypatch.setattr(logosnode_mod, name, {})
    return registry


def _patched_capture(monkeypatch, db):
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_build_live_local_provider_sample", lambda _p, snap: _sample(snap["runtime"]))
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda provider_id: "gpu-1")


def _capture(*runtimes: dict) -> None:
    async def _run():
        for runtime in runtimes:
            await logosnode_mod._capture_logosnode_provider_snapshot(7, runtime)
        await asyncio.gather(*list(logosnode_mod._sample_writers.values()))

    asyncio.run(_run())


def test_a_snapshot_insert_failure_keeps_the_worker_connected(monkeypatch, caplog, registry):
    """The insert is the one statement that can fail here (missing table,
    transient database error). It must not propagate, or the handler detaches
    the worker."""
    _patched_capture(monkeypatch, _SnapshotDB(raises=RuntimeError('relation "provider_snapshots" does not exist')))

    with caplog.at_level("WARNING"):
        _capture({"timestamp": _TS})  # must not raise

    assert "Failed to persist provider snapshot" in caplog.text


def test_scheduling_still_sees_a_sample_the_database_lost(monkeypatch, registry):
    """Scheduler signals are read from memory, so a failed insert must not
    hide the status from them."""
    _patched_capture(monkeypatch, _SnapshotDB(raises=RuntimeError("db down")))

    _capture({"timestamp": _TS})

    assert len(registry.samples) == 1


def test_a_successful_snapshot_is_stored_without_the_profiles(monkeypatch, registry):
    db = _SnapshotDB(snapshot_id=42)
    _patched_capture(monkeypatch, db)

    _capture({"timestamp": _TS, "lanes": [], "model_profiles": {"org/model": {"base_residency_mb": 1.0}}})

    assert db.inserted["provider_id"] == 7
    assert db.inserted["runtime_payload"] == {"timestamp": _TS, "lanes": []}
    assert len(registry.samples) == 1


def test_the_database_work_runs_off_the_event_loop_thread(monkeypatch, registry):
    """Every worker's session shares the loop; a slow insert must not stall it."""
    db = _SnapshotDB()
    _patched_capture(monkeypatch, db)

    _capture({"timestamp": _TS})

    assert db.thread is not None
    assert db.thread != threading.get_ident()


def test_statuses_waiting_for_the_writer_collapse_into_the_newest(monkeypatch, registry):
    db = _SnapshotDB()
    _patched_capture(monkeypatch, db)

    _capture({"timestamp": _TS, "lanes": ["old"]}, {"timestamp": "2026-09-03T12:00:01+00:00", "lanes": ["new"]})

    assert [insert["runtime_payload"]["lanes"] for insert in db.inserts] == [["new"]]
    assert len(registry.samples) == 2


def test_count_only_statuses_are_written_at_most_once_per_interval(monkeypatch, registry):
    """A request count change resends the previous status unchanged except
    for its counters; memory keeps each one, the database one per interval."""
    db = _SnapshotDB()
    _patched_capture(monkeypatch, db)
    persisted: list = []
    original = logosnode_mod._persist_logosnode_status

    def _spy(provider_id, sample, count_only=False):
        persisted.append(count_only)
        return original(provider_id, sample, count_only)

    monkeypatch.setattr(logosnode_mod, "_persist_logosnode_status", _spy)

    _capture({"timestamp": _TS})
    _capture({"timestamp": _TS}, {"timestamp": _TS})
    assert persisted == [False]
    assert len(registry.samples) == 3

    logosnode_mod._last_snapshot_at[7] -= logosnode_mod._COUNT_ONLY_SNAPSHOT_SECONDS
    _capture({"timestamp": _TS})
    assert persisted == [False, True]


def test_an_accepted_status_ends_the_resync_backoff(monkeypatch, registry):
    _patched_capture(monkeypatch, _SnapshotDB())
    logosnode_mod._resync_rounds[7] = 4

    _capture({"timestamp": _TS})

    assert 7 not in logosnode_mod._resync_rounds
