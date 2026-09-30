"""Guards in the central model-profile queries."""

from __future__ import annotations

import datetime
import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from logos.dbutils.dbmanager import DBManager


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


def test_echo_is_only_applied_at_the_stored_revision():
    db = _db()
    db.session.execute.return_value = SimpleNamespace(rowcount=0)
    applied = db.persist_central_model_profile(7, "org/model", {"base_residency_mb": 1.0}, 3, "H1")
    assert applied is False
    _sql, params = db.session.execute.call_args.args
    # Checked against the source: the unit-test conftest stubs sqlalchemy.
    source = inspect.getsource(DBManager.persist_central_model_profile)
    assert "WHERE model_profiles.sync_revision = EXCLUDED.sync_revision" in source
    assert params["sync_revision"] == 3
    assert json.loads(params["profile"]) == {"base_residency_mb": 1.0}
    assert params["base_residency_mb"] == 1.0


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
    assert "calibration_id IS DISTINCT FROM :calibration_id" in inspect.getsource(DBManager.record_model_calibration)
    assert link_params["calibration_id"] == 11
