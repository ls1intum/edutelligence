"""Guards in the central model-profile queries."""

from __future__ import annotations

import datetime
import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from logos.dbutils.dbmanager import (
    _CENTRAL_PROFILE_ROW,
    _RESET_PROFILE_COLUMNS,
    DBManager,
    _model_profile_column_params,
    _upsert_model_profile_sql,
)
from logos.dbutils.dbrequest import LogosNodeModelProfilesRequest


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


def test_echo_is_only_applied_at_the_stored_revision():
    db = _db()
    db.session.execute.return_value = SimpleNamespace(rowcount=0)
    applied = db.persist_central_model_profile(
        7,
        "org/model",
        {"base_residency_mb": 1.0},
        {"base_residency_mb": 1.0, "max_context_length": 131072},
        3,
        "H1",
    )
    assert applied is False
    _sql, params = db.session.execute.call_args.args
    # Checked against the source: the unit-test conftest stubs sqlalchemy.
    source = inspect.getsource(DBManager.persist_central_model_profile)
    assert 'where="model_profiles.sync_revision = EXCLUDED.sync_revision"' in source
    assert params["sync_revision"] == 3
    assert json.loads(params["profile"]) == {"base_residency_mb": 1.0}
    assert params["max_reported_context_length"] == 131072


def test_echo_without_a_key_hash_keeps_the_reported_one():
    source = inspect.getsource(DBManager.persist_central_model_profile)
    assert "COALESCE(EXCLUDED.calibration_key_hash, model_profiles.calibration_key_hash)" in source


def test_upsert_sql_guards_and_keeps_the_context_high_water_mark():
    sql = _upsert_model_profile_sql(
        extra={"sync_revision": ":sync_revision"},
        conflict_set={"profile": "EXCLUDED.profile"},
        where="model_profiles.sync_revision = EXCLUDED.sync_revision",
    )
    assert sql.endswith("WHERE model_profiles.sync_revision = EXCLUDED.sync_revision")
    assert "max_reported_context_length = GREATEST(COALESCE(model_profiles.max_reported_context_length, 0)" in sql
    assert "profile = EXCLUDED.profile" in sql
    assert ":sync_revision" in sql
    assert "sync_revision = EXCLUDED" not in sql.split(" WHERE ")[0]


def test_known_calibration_is_linked_without_a_new_snapshot():
    db = _db()
    select_result = MagicMock()
    select_result.scalar_one.return_value = 11
    db.session.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),
        select_result,
        MagicMock(fetchone=MagicMock(return_value=None)),
    ]
    revision = db.record_model_calibration(
        7,
        "org/model",
        {"base_residency_mb": 1.0},
        {"backend": "cuda"},
        "H1",
        datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc),
    )
    assert revision is None
    _sql, link_params = db.session.execute.call_args_list[2].args
    assert "calibration_id IS DISTINCT FROM :calibration_id" in inspect.getsource(DBManager._link_calibration)
    assert link_params["calibration_id"] == 11


def test_profile_emptied_by_a_central_change_stays_central():
    """Clearing the only verdict of an unsupported-only profile leaves {}
    at a bumped revision; the worker must still be sent that empty state."""
    assert "OR mp.sync_revision > 0" in _CENTRAL_PROFILE_ROW
    for method in (DBManager.get_central_model_profiles, DBManager.import_legacy_model_profiles):
        assert "_CENTRAL_PROFILE_ROW" in inspect.getsource(method)


def test_malformed_worker_values_bind_as_null_instead_of_failing():
    params = _model_profile_column_params(
        {
            "base_residency_mb": "lots",
            "measurement_count": "n/a",
            "tensor_parallel_size": "2",
            "engine": 3,
            "last_measured_epoch": 1e300,
        }
    )
    assert params["base_residency_mb"] is None
    assert params["measurement_count"] == 0
    assert params["tensor_parallel_size"] == 2
    assert params["engine"] is None
    assert params["last_measured_at"] is None


def test_profile_requests_are_bounded():
    with pytest.raises(ValidationError):
        LogosNodeModelProfilesRequest(shared_key="k", calibration_key_hashes={str(i): "h" for i in range(1001)})


def test_reset_is_a_revision_bump_that_keeps_the_context_high_water_mark():
    source = inspect.getsource(DBManager.reset_model_profiles)
    assert "sync_revision = sync_revision + 1" in source
    assert "DELETE" not in source
    assert "max_reported_context_length" not in _RESET_PROFILE_COLUMNS
    assert {"base_residency_mb", "residency_source", "last_measured_at"} <= set(_RESET_PROFILE_COLUMNS)
