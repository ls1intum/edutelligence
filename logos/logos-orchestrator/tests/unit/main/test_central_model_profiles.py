"""Worker profile persistence and sync through the central database."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import WebSocketDisconnect

import logos as main_mod
from logos.dbutils.dbrequest import (
    LogosKeyModel,
    LogosNodeCalibrationReservationRequest,
    LogosNodeClearUnsupportedRequest,
    LogosNodeInvalidateCalibrationRequest,
    LogosNodeModelProfilesRequest,
    LogosNodeResetProfilesRequest,
)
from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession
from logos.model_profile_store import ProfileWriteCache
from logos.routers import logosnode as logosnode_mod

_CALIBRATED = {
    "base_residency_mb": 15000.0,
    "residency_source": "calibrated",
    "calibration_origin": "local",
    "calibration_key_hash": "H1",
    "calibration_key": {"backend": "cuda", "gpu_name": "RTX A4000", "vllm_version": "0.30.0"},
    "last_measured_epoch": 1790000000.0,
    "sync_revision": 0,
}


class _FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _FakeDB:
    def __init__(self, *, accept: bool = True, new_revision: int | None = 1):
        self.session = _FakeSession()
        self.accept = accept
        self.new_revision = new_revision
        self.legacy_upserts: list = []
        self.persisted: list = []
        self.calibrations: list = []
        self.imports: list = []
        self.reported_keys: list = []
        self.cleared: list = []
        self.invalidated: list = []
        self.adopted: list = []
        self.sibling_adopters: dict = {}
        self.rejected: list = []
        self.reject_result: list = []
        self.adoptions: list = [("org/model", 11)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def upsert_model_profiles(self, provider_id, profiles):
        self.legacy_upserts.append((provider_id, profiles))

    def persist_central_model_profile(
        self, provider_id, model_name, profile, reported, revision, key_hash, overridden_fields=None
    ):
        self.persisted.append((provider_id, model_name, profile, revision, key_hash))
        self.overridden = overridden_fields
        self.reported = reported
        return self.accept

    def record_model_calibration(
        self, provider_id, model_name, snapshot, key, key_hash, calibrated_at, duration_s=None
    ):
        self.calibrations.append((provider_id, model_name, snapshot, key, key_hash, calibrated_at))
        self.durations = getattr(self, "durations", []) + [duration_s]
        return self.new_revision

    def import_legacy_model_profiles(self, provider_id, profiles, unsupported):
        self.imports.append((provider_id, profiles, unsupported))
        return len(profiles)

    def update_reported_calibration_keys(self, provider_id, key_hashes, slice_gpu_counts=None):
        self.reported_keys.append((provider_id, key_hashes))
        self.slice_counts = slice_gpu_counts

    def adopt_shared_calibrations(self, provider_id, model_names, max_age_days, adopt=True):
        self.adopted.append((provider_id, model_names, max_age_days, adopt))
        return self.adoptions if adopt else []

    def adopt_shared_calibration_for_siblings(self, provider_id, model_name, max_age_days, skip=None):
        return [(p, c) for p, c in self.sibling_adopters.get(model_name, []) if skip is None or not skip(p)]

    def reject_shared_calibration(self, provider_id, model_name, calibration_id):
        self.rejected.append((provider_id, model_name, calibration_id))
        return self.reject_result

    def get_central_model_profiles(self, provider_id, model_names=None):
        return [
            {
                "model_name": "org/model",
                "profile": {"base_residency_mb": 15000.0},
                "sync_revision": 2,
                "calibration_key_hash": "H1",
                "cal_id": None,
                "cal_key_hash": None,
                "cal_source_provider_id": None,
                "cal_invalidated_at": None,
            }
        ]

    def clear_calibration_unsupported(self, provider_id, model_name):
        self.cleared.append((provider_id, model_name))
        return 4

    def reset_model_profiles(self, provider_id, model_names=None):
        self.reset = (provider_id, model_names)
        return list(model_names or ["org/model"])

    def invalidate_model_calibration(self, calibration_id, reason):
        self.invalidated.append((calibration_id, reason))
        return [(1, "org/model"), (2, "org/model")]


class _FakeRegistry:
    def __init__(self, supported: bool):
        self.supported = supported
        self.sent: list = []

    def supports_action(self, provider_id, action):
        return self.supported

    async def send_command(self, provider_id, action, params=None, timeout_seconds=20):
        self.sent.append((provider_id, action, params))
        return {"ok": True}


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    monkeypatch.setattr(logosnode_mod, "_profile_write_cache", ProfileWriteCache())
    monkeypatch.setattr(logosnode_mod, "_recorded_calibrations", {})


def test_profiles_from_a_worker_with_a_local_file_are_only_mirrored():
    db = _FakeDB()
    changed, rejected = logosnode_mod._persist_model_profiles(db, 1, {"org/model": {"base_residency_mb": 1.0}})
    assert (changed, rejected) == ([], [])
    assert db.legacy_upserts == [(1, {"org/model": {"base_residency_mb": 1.0}})]
    assert db.persisted == []


def test_mirror_writes_only_profiles_that_changed():
    db = _FakeDB()
    first = {"a": {"base_residency_mb": 1.0}, "b": {"base_residency_mb": 2.0}}
    logosnode_mod._persist_model_profiles(db, 1, first)
    logosnode_mod._persist_model_profiles(db, 1, {"a": {"base_residency_mb": 1.0}, "b": {"base_residency_mb": 3.0}})
    logosnode_mod._persist_model_profiles(db, 1, {"a": {"base_residency_mb": 1.0}, "b": {"base_residency_mb": 3.0}})
    assert db.legacy_upserts == [(1, first), (1, {"b": {"base_residency_mb": 3.0}})]


def test_overrides_reach_the_typed_columns_but_not_the_stored_profile():
    db = _FakeDB()
    echoed = {
        "base_residency_mb": 1.0,
        "max_context_length": 131072,
        "overridden_fields": ["max_context_length"],
        "sync_revision": 0,
    }
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": echoed})
    assert db.persisted[0][2] == {"base_residency_mb": 1.0}
    assert db.reported == {"base_residency_mb": 1.0, "max_context_length": 131072}


def test_central_echo_is_stored_without_sync_metadata():
    db = _FakeDB()
    echoed = {"base_residency_mb": 1.0, "sync_revision": 3, "calibration_stale": False}
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": echoed})
    assert db.persisted == [(1, "org/model", {"base_residency_mb": 1.0}, 3, None)]


def test_unchanged_echo_is_written_once():
    db = _FakeDB()
    echoed = {"base_residency_mb": 1.0, "sync_revision": 3}
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": echoed})
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(echoed)})
    assert len(db.persisted) == 1


def test_rejected_echo_is_retried_and_records_no_calibration():
    db = _FakeDB(accept=False)
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    changed, rejected = logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert (changed, rejected) == ([], ["org/model"])
    assert len(db.persisted) == 2
    assert db.calibrations == []


def test_rejected_echoes_share_one_resync_push(monkeypatch):
    pushed: list = []

    async def _push(provider_id, model_names=None, calibration_key_hashes=None):
        pushed.append((provider_id, model_names))

    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)
    monkeypatch.setattr(logosnode_mod, "_pending_resyncs", {})
    monkeypatch.setattr(logosnode_mod, "_RESYNC_DELAY_SECONDS", 0)

    async def _scenario():
        logosnode_mod._schedule_model_profile_resync(1, ["a"])
        logosnode_mod._schedule_model_profile_resync(1, ["b", "a"])
        logosnode_mod._schedule_model_profile_resync(2, ["c"])
        await asyncio.gather(*list(main_mod._background_tasks))
        logosnode_mod._schedule_model_profile_resync(1, ["a"])
        await asyncio.gather(*list(main_mod._background_tasks))

    asyncio.run(_scenario())
    assert sorted(pushed) == [(1, ["a"]), (1, ["a", "b"]), (2, ["c"])]
    assert logosnode_mod._pending_resyncs == {}


def test_fresh_calibration_is_snapshotted_once_and_pushed_back():
    db = _FakeDB(new_revision=1)
    changed, rejected = logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert (changed, rejected) == (["org/model"], [])
    provider_id, model_name, snapshot, key, key_hash, calibrated_at = db.calibrations[0]
    assert (provider_id, model_name, key_hash) == (1, "org/model", "H1")
    assert snapshot == {
        "base_residency_mb": 15000.0,
        "residency_source": "calibrated",
        "last_measured_epoch": 1790000000.0,
    }
    assert key["gpu_name"] == "RTX A4000"
    assert calibrated_at.timestamp() == 1790000000.0

    again, _ = logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert again == []
    assert len(db.calibrations) == 1


def test_push_is_skipped_for_workers_without_the_sync_action(monkeypatch):
    registry = _FakeRegistry(supported=False)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    asyncio.run(logosnode_mod._push_model_profiles(1))
    assert registry.sent == []


def test_push_sends_effective_profiles(monkeypatch):
    registry = _FakeRegistry(supported=True)
    db = _FakeDB()
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-1")
    asyncio.run(logosnode_mod._push_model_profiles(1, ["org/model"], {"org/model": "H1"}))
    assert db.reported_keys == [(1, {"org/model": "H1"})]
    provider_id, action, params = registry.sent[0]
    assert action == "sync_model_profiles"
    assert set(params) == {"profiles"}
    assert params["profiles"]["org/model"]["sync_revision"] == 2


def test_push_failure_keeps_the_session(monkeypatch):
    registry = _FakeRegistry(supported=True)

    async def _broken(*a, **k):
        raise RuntimeError("socket closed")

    registry.send_command = _broken
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: _FakeDB())
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-1")
    asyncio.run(logosnode_mod._push_model_profiles(1))


def test_startup_endpoint_imports_legacy_file_and_returns_profiles(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_require_tls_request", lambda request: None)
    monkeypatch.setattr(logosnode_mod, "_logosnode_provider_for_key", lambda key: {"id": 5})
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-5")
    data = LogosNodeModelProfilesRequest(
        shared_key="k",
        calibration_key_hashes={"org/model": "H1"},
        legacy_import={"model_profiles": {"org/model": {"base_residency_mb": 1.0}}, "unsupported_models": {}},
    )
    result = asyncio.run(logosnode_mod.logosnode_model_profiles(data, request=None))
    assert db.imports == [(5, {"org/model": {"base_residency_mb": 1.0}}, {})]
    assert db.reported_keys == [(5, {"org/model": "H1"})]
    assert result["profiles"]["org/model"]["sync_revision"] == 2


def test_clear_unsupported_pushes_the_model(monkeypatch):
    db = _FakeDB()
    pushed: list = []

    async def _push(provider_id, model_names=None, calibration_key_hashes=None):
        pushed.append((provider_id, model_names))

    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: None)
    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)
    data = LogosNodeClearUnsupportedRequest(logos_key="k", provider_id=1, model_name="org/model")
    result = asyncio.run(logosnode_mod.logosnode_clear_unsupported(data))
    assert result["sync_revision"] == 4
    assert pushed == [(1, ["org/model"])]


def test_invalidation_pushes_every_affected_node(monkeypatch):
    db = _FakeDB()
    pushed: list = []

    async def _push(provider_id, model_names=None, calibration_key_hashes=None):
        pushed.append((provider_id, model_names))

    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: None)
    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)
    data = LogosNodeInvalidateCalibrationRequest(logos_key="k", calibration_id=9, reason="wrong footprint")
    result = asyncio.run(logosnode_mod.logosnode_invalidate_calibration(data))
    assert db.invalidated == [(9, "wrong footprint")]
    assert pushed == [(1, ["org/model"]), (2, ["org/model"])]
    assert len(result["affected"]) == 2


def test_reset_is_a_central_change_pushed_to_the_worker(monkeypatch):
    """No 409 any more: the bumped revision rejects the worker's old echoes,
    so a running worker cannot write the reset profiles back."""
    db = _FakeDB()
    pushed: list = []

    async def _push(provider_id, model_names=None, calibration_key_hashes=None):
        pushed.append((provider_id, model_names))

    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: None)
    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)
    logosnode_mod._recorded_calibrations[(1, "org/model")] = 1.0
    logosnode_mod._profile_write_cache.remember(1, "org/model", "d")
    data = LogosNodeResetProfilesRequest(logos_key="k", provider_id=1, model_names=["org/model"])
    result = asyncio.run(logosnode_mod.logosnode_reset_profiles(data))
    assert db.reset == (1, ["org/model"])
    assert result == {"provider_id": 1, "reset": ["org/model"], "shared_profiles": True}
    assert pushed == [(1, ["org/model"])]
    assert (1, "org/model") not in logosnode_mod._recorded_calibrations
    assert not logosnode_mod._profile_write_cache.unchanged(1, "org/model", "d")


def test_profiles_of_one_status_are_committed_once():
    db = _FakeDB()
    echoes = {name: {"base_residency_mb": 1.0, "sync_revision": 0} for name in ("a", "b", "c")}
    logosnode_mod._persist_model_profiles(db, 1, echoes)
    assert len(db.persisted) == 3
    assert db.session.commits == 1


def test_a_rolled_back_status_is_not_remembered_as_stored():
    """The write cache may only skip what reached the database."""

    class _FailingDB(_FakeDB):
        def record_model_calibration(self, *args):
            raise RuntimeError("db down")

    db = _FailingDB()
    with pytest.raises(RuntimeError):
        logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert db.session.commits == 0
    assert logosnode_mod._recorded_calibrations == {}
    retry = _FakeDB()
    logosnode_mod._persist_model_profiles(retry, 1, {"org/model": dict(_CALIBRATED)})
    assert len(retry.persisted) == 1
    assert len(retry.calibrations) == 1


def test_a_loaded_lane_rewrites_its_row_only_once_per_flush_interval(monkeypatch):
    """Every status of a loaded lane bumps the measurement counters; those
    alone are written lazily, a real change at once."""
    clock = [1000.0]
    monkeypatch.setattr(logosnode_mod.time, "monotonic", lambda: clock[0])
    db = _FakeDB()

    def _echo(count: int, loaded: float = 15000.0) -> dict:
        return {
            "loaded_vram_mb": loaded,
            "measurement_count": count,
            "last_measured_epoch": float(count),
            "sync_revision": 2,
        }

    logosnode_mod._persist_model_profiles(db, 1, {"org/model": _echo(1)})
    clock[0] += 60
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": _echo(2)})
    assert len(db.persisted) == 1
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": _echo(3, loaded=17000.0)})
    assert len(db.persisted) == 2
    clock[0] += logosnode_mod._profile_write_cache._flush_seconds  # noqa: SLF001
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": _echo(4, loaded=17000.0)})
    assert len(db.persisted) == 3


def test_resyncs_back_off_while_the_worker_keeps_rejecting(monkeypatch):
    delays: list = []

    async def _resync(provider_id, delay=0.0):
        delays.append(delay)

    monkeypatch.setattr(logosnode_mod, "_run_model_profile_resync", _resync)
    monkeypatch.setattr(logosnode_mod, "_pending_resyncs", {})
    monkeypatch.setattr(logosnode_mod, "_resync_rounds", {})

    async def _run():
        for _ in range(8):
            logosnode_mod._schedule_model_profile_resync(1, ["org/model"])
            await asyncio.sleep(0)
            logosnode_mod._pending_resyncs.pop(1, None)

    asyncio.run(_run())
    assert delays == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0]


def test_overridden_fields_are_passed_on_so_their_stored_values_survive():
    db = _FakeDB()
    echo = {"max_context_length": 32768, "overridden_fields": ["max_context_length"], "sync_revision": 1}
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": echo})
    assert db.persisted[0][2] == {}
    assert db.overridden == ["max_context_length"]


def test_a_finished_session_leaves_no_bookkeeping_behind(monkeypatch):
    for name in ("_last_runtime_ts", "_last_snapshot_at", "_resync_rounds", "_pending_resyncs"):
        monkeypatch.setattr(logosnode_mod, name, {1: "x", 2: "y"})
    logosnode_mod._recorded_calibrations.update({(1, "a"): 1.0, (2, "a"): 2.0})
    logosnode_mod._profile_write_cache.remember(1, "a", "d")
    logosnode_mod._profile_write_cache.remember(2, "a", "d")

    logosnode_mod._forget_provider_state(1)

    for name in ("_last_runtime_ts", "_last_snapshot_at", "_resync_rounds", "_pending_resyncs"):
        assert getattr(logosnode_mod, name) == {2: "y"}
    assert logosnode_mod._recorded_calibrations == {(2, "a"): 2.0}
    assert not logosnode_mod._profile_write_cache.unchanged(1, "a", "d")
    assert logosnode_mod._profile_write_cache.unchanged(2, "a", "d")


class _EndedSessionRegistry:
    def __init__(self, newer_session: bool):
        self.newer_session = newer_session

    async def consume_ticket(self, token):
        return SimpleNamespace(provider_id=1, worker_id="w")

    async def attach_session(self, ticket, websocket):
        return SimpleNamespace(session_id="s1")

    async def detach_session(self, provider_id, websocket=None):
        return None

    def peek_runtime_snapshot(self, provider_id):
        return {"session_id": "s2"} if self.newer_session else None


class _DisconnectingSocket:
    async def accept(self):
        return None

    async def receive_json(self):
        raise WebSocketDisconnect()


@pytest.mark.parametrize("newer_session", [False, True])
def test_only_a_session_without_successor_drops_the_bookkeeping(monkeypatch, newer_session):
    """A replaced socket ends after its successor attached; it must not
    wipe the state the new session already builds up."""
    monkeypatch.setattr(main_mod, "_logosnode_registry", _EndedSessionRegistry(newer_session))
    monkeypatch.setattr(logosnode_mod, "_is_tls_websocket", lambda websocket: True)
    monkeypatch.setattr(logosnode_mod, "_last_runtime_ts", {1: "ts"})

    asyncio.run(logosnode_mod.logosnode_session(_DisconnectingSocket(), token="t"))

    assert (1 in logosnode_mod._last_runtime_ts) is newer_session


def test_a_reset_landing_between_commit_and_cache_update_is_not_masked():
    """The status write commits, a reset commits and forgets, then the
    writer updates the cache: the old echo must still reach the database."""

    class _ResetRacingDB(_FakeDB):
        def persist_central_model_profile(self, provider_id, model_name, *args):
            accepted = super().persist_central_model_profile(provider_id, model_name, *args)
            logosnode_mod._profile_write_cache.forget(provider_id, model_name)
            return accepted

    echo = {"org/model": {"base_residency_mb": 1.0, "sync_revision": 3}}
    logosnode_mod._persist_model_profiles(_ResetRacingDB(), 1, echo)
    later = _FakeDB(accept=False)
    _, rejected = logosnode_mod._persist_model_profiles(later, 1, echo)
    assert len(later.persisted) == 1
    assert rejected == ["org/model"]


def test_the_admin_endpoints_check_the_root_key_off_the_event_loop(monkeypatch):
    """The loop also relays every worker's stream; a slow key lookup must
    not stall it."""
    threads: list = []
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: _FakeDB())
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: threads.append(threading.get_ident()))

    async def _push(provider_id, model_names=None, calibration_key_hashes=None):
        return None

    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)

    async def _run():
        loop_thread = threading.get_ident()
        await logosnode_mod.logosnode_clear_unsupported(
            LogosNodeClearUnsupportedRequest(logos_key="k", provider_id=1, model_name="org/model")
        )
        await logosnode_mod.logosnode_invalidate_calibration(
            LogosNodeInvalidateCalibrationRequest(logos_key="k", calibration_id=9)
        )
        await logosnode_mod.logosnode_reset_profiles(LogosNodeResetProfilesRequest(logos_key="k", provider_id=1))
        return loop_thread

    loop_thread = asyncio.run(_run())
    assert len(threads) == 3
    assert loop_thread not in threads


def test_a_reported_key_lets_the_node_adopt_a_shared_calibration(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-5")
    logosnode_mod._update_reported_calibration_keys(5, {"org/model": "H1"}, {"org/model": 2})
    assert db.slice_counts == {"org/model": 2}
    assert db.adopted == [(5, ["org/model"], 30, True)]


def test_sharing_can_be_switched_off(monkeypatch):
    db = _FakeDB()
    monkeypatch.setenv("LOGOS_SHARED_PROFILES", "0")
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    logosnode_mod._update_reported_calibration_keys(5, {"org/model": "H1"}, {"org/model": 2})
    assert db.reported_keys
    assert db.adopted == [(5, ["org/model"], 30, False)]  # a misfit calibration is still dropped
    assert logosnode_mod._offer_calibrations_to_siblings(5, ["org/model"]) == {}


def test_a_fresh_calibration_is_offered_to_the_nodes_of_its_key(monkeypatch):
    db = _FakeDB()
    db.sibling_adopters = {"org/model": [(7, 21), (8, None)]}
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: f"gpu-{pid}")
    assert logosnode_mod._offer_calibrations_to_siblings(5, ["org/model", "other"]) == {
        7: ["org/model"],
        8: ["org/model"],
    }


def test_a_node_calibrating_the_model_is_not_offered_one(monkeypatch):
    db = _FakeDB()
    db.sibling_adopters = {"org/model": [(7, 21), (8, 21)]}
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: f"gpu-{pid}")
    monkeypatch.setattr(
        logosnode_mod, "_models_in_calibration", lambda pid: frozenset({"org/model"}) if pid == 7 else frozenset()
    )
    assert logosnode_mod._offer_calibrations_to_siblings(5, ["org/model"]) == {8: ["org/model"]}


def test_a_reconnecting_node_does_not_adopt_the_model_it_is_calibrating(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-5")
    monkeypatch.setattr(logosnode_mod, "_models_in_calibration", lambda pid: frozenset({"org/busy"}))
    logosnode_mod._update_reported_calibration_keys(5, {"org/busy": "H1", "org/idle": "H2"}, {})
    assert db.adopted == [(5, ["org/idle"], 30, True)]


def test_a_reset_says_whether_calibration_sharing_is_on(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: None)

    async def _push(*args, **kwargs):
        return None

    monkeypatch.setattr(logosnode_mod, "_push_model_profiles", _push)
    data = LogosNodeResetProfilesRequest(logos_key="k", provider_id=1, model_names=["org/model"])
    assert asyncio.run(logosnode_mod.logosnode_reset_profiles(data))["shared_profiles"] is True
    monkeypatch.setenv("LOGOS_SHARED_PROFILES", "0")
    assert asyncio.run(logosnode_mod.logosnode_reset_profiles(data))["shared_profiles"] is False


def test_the_calibration_duration_is_stored_with_the_snapshot(monkeypatch):
    db = _FakeDB()
    echoed = dict(_CALIBRATED, calibration_duration_s=412.5)
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": echoed})
    assert db.durations == [412.5]


def test_a_rejected_shared_calibration_is_pushed_to_every_node_that_lost_it(monkeypatch):
    db = _FakeDB()
    db.reject_result = [(1, "org/model"), (2, "org/model")]
    pushed: list = []
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: f"gpu-{pid}")
    monkeypatch.setattr(
        logosnode_mod, "_schedule_model_profile_push", lambda pid, names=None: pushed.append((pid, names))
    )

    async def _run():
        await logosnode_mod._handle_calibration_rejected(2, {"model": "org/model", "details": "11"})

    asyncio.run(_run())
    assert db.rejected == [(2, "org/model", 11)]
    assert pushed == [(1, ["org/model"]), (2, ["org/model"])]


def test_a_rejection_without_a_calibration_id_is_ignored(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    asyncio.run(logosnode_mod._handle_calibration_rejected(2, {"model": "org/model", "details": "n/a"}))
    assert db.rejected == []


def test_gpu_counts_from_the_worker_are_kept_only_when_positive_integers():
    assert logosnode_mod._int_map({"a": 2, "b": 0, "c": "3", "d": True, "e": -1}) == {"a": 2}
    assert logosnode_mod._int_map(None) == {}


def test_a_failing_adoption_never_keeps_a_worker_from_its_profiles(monkeypatch):
    class _BrokenAdoption(_FakeDB):
        def adopt_shared_calibrations(self, provider_id, model_names, max_age_days):
            raise RuntimeError("sql error")

    db = _BrokenAdoption()
    rollbacks: list = []
    db.session.rollback = lambda: rollbacks.append(1)
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    logosnode_mod._update_reported_calibration_keys(5, {"org/model": "H1"}, {"org/model": 2})
    assert db.reported_keys == [(5, {"org/model": "H1"})]
    assert rollbacks == [1]


def test_the_sharing_setting_can_be_read_without_changing_it(monkeypatch):
    monkeypatch.setattr(logosnode_mod, "_require_root_access", lambda key: None)
    data = LogosKeyModel(logos_key="k")
    result = asyncio.run(logosnode_mod.logosnode_calibration_sharing(data))
    assert result == {"shared_profiles": True, "max_age_days": 30}
    monkeypatch.setenv("LOGOS_SHARED_PROFILES", "0")
    assert asyncio.run(logosnode_mod.logosnode_calibration_sharing(data))["shared_profiles"] is False


def test_a_linked_snapshot_lifts_the_protection_of_a_finished_model(monkeypatch):
    lifted: list = []
    monkeypatch.setattr(
        main_mod,
        "_logosnode_registry",
        SimpleNamespace(snapshots_linked=lambda pid, models: lifted.append((pid, models))),
    )
    logosnode_mod._snapshots_linked(5, ["org/model"])
    assert lifted == [(5, ["org/model"])]
    monkeypatch.setattr(main_mod, "_logosnode_registry", None)
    logosnode_mod._snapshots_linked(5, ["org/model"])  # no registry: nothing to lift
    assert logosnode_mod._models_in_calibration(5) == frozenset()


def _registry_with_sessions(*provider_ids):
    registry = LogosNodeRuntimeRegistry()
    for pid in provider_ids:
        session = ProviderSession(provider_id=pid, worker_id=f"w{pid}", websocket=MagicMock())
        registry._sessions[pid] = session  # noqa: SLF001
    return registry


def _reservation_endpoint(monkeypatch, provider_id=5):
    monkeypatch.setattr(logosnode_mod, "_require_tls_request", lambda request: None)
    monkeypatch.setattr(logosnode_mod, "_logosnode_provider_for_key", lambda key: {"id": provider_id})
    data = LogosNodeCalibrationReservationRequest(shared_key="k", model_name="org/model")
    return lambda: asyncio.run(logosnode_mod.logosnode_calibration_reservation(data, request=None))


def test_a_reservation_answers_with_the_profile_and_bars_adoption(monkeypatch):
    registry = _registry_with_sessions(5)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    monkeypatch.setattr(
        logosnode_mod, "_load_effective_profiles", lambda pid, names=None: {"org/model": {"sync_revision": 4}}
    )
    reserve = _reservation_endpoint(monkeypatch)
    assert reserve() == {"profiles": {"org/model": {"sync_revision": 4}}}
    assert registry.models_in_calibration(5) == frozenset({"org/model"})


def test_a_node_that_reserved_a_model_is_not_offered_one_before_its_events_arrive(monkeypatch):
    """Event delivery is delayed: no calibration_model_selected has been seen,
    yet a sibling finishing now must not be adopted by the reserving node."""
    registry = _registry_with_sessions(7, 8)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    db = _FakeDB()
    db.sibling_adopters = {"org/model": [(7, 21), (8, 21)]}
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: f"gpu-{pid}")

    assert logosnode_mod._offer_calibrations_to_siblings(5, ["org/model"]) == {  # noqa: SLF001
        7: ["org/model"],
        8: ["org/model"],
    }
    registry.reserve_calibration(7, "org/model")
    assert logosnode_mod._offer_calibrations_to_siblings(5, ["org/model"]) == {8: ["org/model"]}  # noqa: SLF001


def test_a_reservation_waits_for_an_adoption_in_flight_and_answers_after_it(monkeypatch):
    """An adoption that already checked for a reservation commits first, and
    the answer then carries what it changed; none can slip in afterwards."""
    started, release = threading.Event(), threading.Event()
    state = {"adopted": False}

    class _SlowAdoption(_FakeDB):
        def adopt_shared_calibrations(self, provider_id, model_names, max_age_days, adopt=True):
            started.set()
            release.wait(5)
            state["adopted"] = True
            return [("org/model", 11)]

    registry = _registry_with_sessions(5)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: _SlowAdoption())
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-5")
    monkeypatch.setattr(
        logosnode_mod, "_load_effective_profiles", lambda pid, names=None: {"org/model": {"adopted": state["adopted"]}}
    )
    reserve = _reservation_endpoint(monkeypatch)
    adopting = threading.Thread(
        target=lambda: logosnode_mod._update_reported_calibration_keys(5, {"org/model": "H"}, {})  # noqa: SLF001
    )
    adopting.start()
    assert started.wait(5)

    answer: dict = {}
    reserving = threading.Thread(target=lambda: answer.update(reserve()))
    reserving.start()
    reserving.join(0.5)
    assert reserving.is_alive(), "the reservation must wait for the adoption"
    assert registry.models_in_calibration(5) == frozenset()  # not reserved yet

    release.set()
    adopting.join(5)
    reserving.join(5)
    assert answer["profiles"]["org/model"] == {"adopted": True}
    assert registry.models_in_calibration(5) == frozenset({"org/model"})


def test_once_reserved_the_hello_adoption_leaves_the_model_alone(monkeypatch):
    registry = _registry_with_sessions(5)
    registry.reserve_calibration(5, "org/busy")
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    db = _FakeDB()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(logosnode_mod, "_resolve_provider_name", lambda pid: "gpu-5")
    logosnode_mod._update_reported_calibration_keys(5, {"org/busy": "H1", "org/idle": "H2"}, {})  # noqa: SLF001
    assert db.adopted == [(5, ["org/idle"], 30, True)]


def test_a_reservation_stores_the_workers_key_before_judging_the_profile(monkeypatch):
    """A config edit not yet reported through a status: Logos must still mark the
    profile stale, so the worker does not skip the recalibration it needs."""

    class _Db(_FakeDB):
        reported = "OLD"

        def update_reported_calibration_keys(self, provider_id, key_hashes, slice_gpu_counts=None):
            self.reported = key_hashes["org/model"]
            self.slice_counts = slice_gpu_counts

        def get_central_model_profiles(self, provider_id, model_names=None):
            return [
                {
                    "model_name": "org/model",
                    "profile": {"base_residency_mb": 1.0},
                    "sync_revision": 2,
                    "calibration_key_hash": self.reported,
                    "cal_id": 11,
                    "cal_key_hash": "OLD",
                    "cal_source_provider_id": 5,
                    "cal_invalidated_at": None,
                }
            ]

    db = _Db()
    monkeypatch.setattr(logosnode_mod, "DBManager", lambda: db)
    monkeypatch.setattr(main_mod, "_logosnode_registry", _registry_with_sessions(5))
    monkeypatch.setattr(logosnode_mod, "_require_tls_request", lambda request: None)
    monkeypatch.setattr(logosnode_mod, "_logosnode_provider_for_key", lambda key: {"id": 5})

    def reserve(**fields):
        data = LogosNodeCalibrationReservationRequest(shared_key="k", model_name="org/model", **fields)
        return asyncio.run(logosnode_mod.logosnode_calibration_reservation(data, request=None))

    assert reserve()["profiles"]["org/model"]["calibration_stale"] is False  # an older worker
    answer = reserve(calibration_key_hash="NEW", slice_gpu_count=2)
    assert answer["profiles"]["org/model"]["calibration_stale"] is True
    assert (db.reported, db.slice_counts) == ("NEW", {"org/model": 2})
