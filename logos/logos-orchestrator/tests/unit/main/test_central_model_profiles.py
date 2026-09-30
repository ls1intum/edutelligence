"""Worker profile persistence and sync through the central database."""

from __future__ import annotations

import asyncio

import pytest

import logos as main_mod
from logos.dbutils.dbrequest import (
    LogosNodeClearUnsupportedRequest,
    LogosNodeInvalidateCalibrationRequest,
    LogosNodeModelProfilesRequest,
)
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


class _FakeDB:
    def __init__(self, *, accept: bool = True, new_revision: int | None = 1):
        self.accept = accept
        self.new_revision = new_revision
        self.legacy_upserts: list = []
        self.persisted: list = []
        self.calibrations: list = []
        self.imports: list = []
        self.reported_keys: list = []
        self.cleared: list = []
        self.invalidated: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def upsert_model_profiles(self, provider_id, profiles):
        self.legacy_upserts.append((provider_id, profiles))

    def persist_central_model_profile(self, provider_id, model_name, profile, revision, key_hash):
        self.persisted.append((provider_id, model_name, profile, revision, key_hash))
        return self.accept

    def record_model_calibration(self, provider_id, model_name, snapshot, key, key_hash, calibrated_at):
        self.calibrations.append((provider_id, model_name, snapshot, key, key_hash, calibrated_at))
        return self.new_revision

    def import_legacy_model_profiles(self, provider_id, profiles, unsupported):
        self.imports.append((provider_id, profiles, unsupported))
        return len(profiles)

    def update_reported_calibration_keys(self, provider_id, key_hashes):
        self.reported_keys.append((provider_id, key_hashes))

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
    changed = logosnode_mod._persist_model_profiles(db, 1, {"org/model": {"base_residency_mb": 1.0}})
    assert changed == []
    assert db.legacy_upserts == [(1, {"org/model": {"base_residency_mb": 1.0}})]
    assert db.persisted == []


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
    logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert len(db.persisted) == 2
    assert db.calibrations == []


def test_fresh_calibration_is_snapshotted_once_and_pushed_back():
    db = _FakeDB(new_revision=1)
    changed = logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
    assert changed == ["org/model"]
    provider_id, model_name, snapshot, key, key_hash, calibrated_at = db.calibrations[0]
    assert (provider_id, model_name, key_hash) == (1, "org/model", "H1")
    assert snapshot == {
        "base_residency_mb": 15000.0,
        "residency_source": "calibrated",
        "last_measured_epoch": 1790000000.0,
    }
    assert key["gpu_name"] == "RTX A4000"
    assert calibrated_at.timestamp() == 1790000000.0

    again = logosnode_mod._persist_model_profiles(db, 1, {"org/model": dict(_CALIBRATED)})
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
    asyncio.run(logosnode_mod._push_model_profiles(1, ["org/model"], {"org/model": "H1"}))
    assert db.reported_keys == [(1, {"org/model": "H1"})]
    provider_id, action, params = registry.sent[0]
    assert action == "sync_model_profiles"
    assert params["complete"] is False
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
