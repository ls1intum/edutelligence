"""Non-string errors must not crash the metrics UPDATE.

Upstream failures arrive as OpenAI-shaped dicts. psycopg2 cannot adapt a dict,
so writing one turned every failed cloud request into an unhandled 500 that
masked the real status — an upstream authentication error surfaced to the client
as a Logos crash.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from logos import DBManager
from logos.dbutils.dbmanager import _SETTLED_COST_SNAPSHOT_SQL, _stringify_error_message


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


def _captured_params(db):
    assert db.session.execute.call_args is not None
    return db.session.execute.call_args[0][1]


def test_openai_shaped_error_dict_is_stored_as_its_message():
    db = _db()
    db.update_log_entry_metrics(
        log_id=359703,
        result_status="error",
        error_message={"message": "Missing logos key", "type": "authentication_error"},
    )

    params = _captured_params(db)
    assert params["error_message"] == "Missing logos key"
    assert isinstance(params["error_message"], str)
    assert db.session.execute.call_count == 2


def test_error_cost_snapshot_excludes_request_only_quantities():
    assert "le.result_status IN ('error', 'timeout')" in _SETTLED_COST_SNAPSHOT_SQL
    assert "'billed_requests'" in _SETTLED_COST_SNAPSHOT_SQL
    assert "'billed_input_characters'" in _SETTLED_COST_SNAPSHOT_SQL


def test_dict_without_message_is_serialised():
    db = _db()
    db.update_log_entry_metrics(log_id=1, error_message={"type": "api_error"})

    stored = _captured_params(db)["error_message"]
    assert isinstance(stored, str)
    assert json.loads(stored) == {"type": "api_error"}


def test_plain_string_error_is_untouched():
    db = _db()
    db.update_log_entry_metrics(log_id=1, error_message="upstream timeout")

    assert _captured_params(db)["error_message"] == "upstream timeout"


def test_job_status_error_dict_is_coerced():
    db = _db()
    db.update = MagicMock()
    db.update_job_status(7, "failed", error_message={"message": "boom", "type": "api_error"})

    update_data = db.update.call_args[0][2]
    assert update_data["error_message"] == "boom"


def test_stringify_helper_handles_lists_and_scalars():
    assert json.loads(_stringify_error_message([{"message": "a"}])) == [{"message": "a"}]
    assert _stringify_error_message(42) == "42"
    assert _stringify_error_message({"message": ""}) == '{"message":""}'
