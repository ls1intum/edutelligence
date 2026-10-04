"""A NUL byte in a request body must not turn the logging write into a 500.

``json.dumps`` renders a NUL as the one escape sequence Postgres refuses inside
``jsonb``, so a single such byte anywhere in a payload made the insert raise
``UntranslatableCharacter``. It was raised from ``auth_parse_log`` before the
request reached a worker, so a client replaying a conversation that had captured
raw binary output got an instant 500 on every retry — and the request was never
logged either.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from logos import DBManager
from logos.dbutils.dbmanager import _json_for_jsonb, _strip_nul

NUL = chr(0)
# The literal six characters a backslash escape consists of. Text that legitimately
# contains them must survive untouched: after serialisation they look exactly like
# the escape being stripped, which is why the NUL has to go before json.dumps runs.
ESCAPE_TEXT = chr(92) + "u0000"


def _db(fetchone=None):
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    if fetchone is not None:
        db.session.execute.return_value.fetchone.return_value = fetchone
    return db


def _captured_params(db):
    assert db.session.execute.call_args is not None
    return db.session.execute.call_args[0][1]


def test_input_payload_with_nul_is_stored_without_it():
    db = _db()
    db.log_usage(
        api_key_id=88,
        team_id=None,
        user_id=None,
        environment=None,
        log_level="FULL",
        input_payload={"messages": [{"role": "user", "content": "tool output" + NUL * 3}]},
    )

    stored = _captured_params(db)["payload"]
    assert NUL not in stored
    assert json.loads(stored)["messages"][0]["content"] == "tool output"


def test_headers_with_nul_are_stored_without_it():
    db = _db()
    db.log_usage(
        api_key_id=88,
        team_id=None,
        user_id=None,
        environment=None,
        log_level="FULL",
        headers={"x-trace": "abc" + NUL},
    )

    stored = _captured_params(db)["headers"]
    assert NUL not in stored
    assert json.loads(stored)["x-trace"] == "abc"


def test_response_payload_with_nul_is_stored_without_it():
    db = _db(fetchone=("FULL",))
    db.set_response_payload(log_id=1, payload={"text": "answer" + NUL})

    stored = _captured_params(db)["payload"]
    assert NUL not in stored
    assert json.loads(stored)["text"] == "answer"


def test_job_request_payload_with_nul_is_stored_without_it():
    """The async job route persists the same body into a jsonb column."""
    db = _db()
    db.create_job_record(
        payload={"messages": [{"role": "user", "content": "x" + NUL}]},
        api_key_id=88,
        team_id=None,
        user_id=None,
        environment=None,
    )

    stored = _captured_params(db)["payload"]
    assert NUL not in stored
    assert json.loads(stored)["messages"][0]["content"] == "x"


def test_text_that_looks_like_the_escape_is_preserved():
    payload = {"content": "vor" + ESCAPE_TEXT + "nach"}

    restored = json.loads(_json_for_jsonb(payload))

    assert restored == payload


def test_strip_nul_reaches_nested_values_and_keys():
    stripped = _strip_nul(
        {"k" + NUL: ["a" + NUL, {"deep": "b" + NUL}, ("t" + NUL,)]},
    )

    assert stripped == {"k": ["a", {"deep": "b"}, ["t"]]}


def test_strip_nul_leaves_non_strings_alone():
    value = {"n": 1, "f": 1.5, "b": True, "none": None}

    assert _strip_nul(value) == value


def test_job_result_payload_is_sanitised():
    """jobs.result_payload is jsonb and the reflected update binds the dict directly."""
    db = _db()
    db.update = MagicMock()
    db.update_job_status(7, "completed", result_payload={"text": "answer" + NUL})

    update_data = db.update.call_args[0][2]
    assert update_data["result_payload"] == {"text": "answer"}


def test_keys_differing_only_in_nuls_collapse_to_the_last_one():
    """Documented trade-off: a JSON object cannot hold both, and dropping beats a 500."""
    collapsed = _strip_nul({"k" + NUL: "first", "k": "second"})

    assert collapsed == {"k": "second"}
