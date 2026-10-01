"""Guards in the central model-profile queries."""

from __future__ import annotations

import datetime
import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from logos.dbutils.dbmanager import _CENTRAL_PROFILE_ROW, DBManager, _upsert_model_profile_sql


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
