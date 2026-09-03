"""A VRAM snapshot that fails to persist must not drop the worker.

``_capture_logosnode_provider_snapshot`` runs synchronously inside the worker
WebSocket ``status`` handler. If it raised, the exception would propagate out
of that handler and the session would be detached — for every worker. That is
the failure mode of starting the orchestrator before the webservice migration
that (re)creates ``provider_snapshots`` has run, or any transient database
error. The capture is telemetry, so a persistence failure is logged and the
sample is skipped; the worker stays connected and the next status message
retries.
"""

from __future__ import annotations

import logos as main


class _SnapshotDB:
    """Stand-in for ``DBManager`` whose snapshot insert can raise."""

    def __init__(self, *, raises: Exception | None = None, snapshot_id: int = 123):
        self._raises = raises
        self._snapshot_id = snapshot_id
        self.inserted: dict | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def insert_provider_snapshot(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        self.inserted = kwargs
        return self._snapshot_id


def _sample() -> dict:
    return {
        "timestamp": "2026-09-03T12:00:00+00:00",
        "used_vram_mb": 2048.0,
        "total_vram_mb": 49152,
        "remaining_vram_mb": 47104.0,
        "models_loaded": 1,
        "loaded_models": [{"name": "Qwen/Qwen3-8B", "size_vram_mb": 2048}],
        "snapshot_source": "logosnode-runtime",
        "runtime_payload": {},
        "scheduler_signals": {},
    }


def _patched_capture(monkeypatch, db):
    monkeypatch.setattr(main, "DBManager", lambda: db)
    monkeypatch.setattr(main, "_build_live_local_provider_sample", lambda *a, **k: _sample())
    monkeypatch.setattr(main, "_resolve_provider_name", lambda provider_id: "gpu-1")


def test_a_snapshot_insert_failure_keeps_the_worker_connected(monkeypatch, caplog):
    """The insert is the one statement that can fail here (missing table,
    transient database error). It must not propagate, or the handler detaches
    the worker."""
    _patched_capture(monkeypatch, _SnapshotDB(raises=RuntimeError('relation "provider_snapshots" does not exist')))

    with caplog.at_level("WARNING"):
        main._capture_logosnode_provider_snapshot(7, {"timestamp": "2026-09-03T12:00:00+00:00"})  # must not raise

    assert "Failed to persist provider snapshot" in caplog.text


def test_an_insert_failure_is_not_silently_recorded_in_memory(monkeypatch):
    """On a persistence failure the sample is skipped entirely (no in-memory
    recording without a snapshot id) rather than half-committed."""
    db = _SnapshotDB(raises=RuntimeError("db down"))
    _patched_capture(monkeypatch, db)
    created: list = []

    def _create_task(coro, *a, **k):
        created.append(coro)
        coro.close()
        return None

    monkeypatch.setattr(main.asyncio, "create_task", _create_task)

    main._capture_logosnode_provider_snapshot(7, {"timestamp": "2026-09-03T12:00:00+00:00"})  # must not raise

    assert db.inserted is None
    assert created == []


def test_a_successful_snapshot_still_persists_and_is_recorded(monkeypatch):
    """Guard the happy path: the non-fatal wrapper must not swallow a
    successful insert or skip the in-memory recording."""
    db = _SnapshotDB(snapshot_id=42)
    _patched_capture(monkeypatch, db)
    created: list = []

    def _create_task(coro, *a, **k):
        created.append(coro)
        coro.close()
        return None

    monkeypatch.setattr(main.asyncio, "create_task", _create_task)

    main._capture_logosnode_provider_snapshot(7, {"timestamp": "2026-09-03T12:00:00+00:00"})

    assert db.inserted is not None
    assert db.inserted["provider_id"] == 7
    assert len(created) == 1
