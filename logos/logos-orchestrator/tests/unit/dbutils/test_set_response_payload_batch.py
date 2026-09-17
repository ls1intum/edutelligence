"""Token-type bookkeeping in set_response_payload must be O(1) roundtrips (#980).

The old code paid a SELECT (plus INSERT + commit) per token type, so a response
with three usage figures meant seven extra roundtrips on the event loop. The
batched version must do one lookup for all names, one upsert for the missing
types (auto-creation is preserved, e.g. Whisper's audio_milliseconds), one
multi-row upsert for the non-zero usage rows, and a single commit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from logos import DBManager


def _exec(fetchone=None, fetchall=None):
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall
    return result


def _type_row(type_id, name):
    return SimpleNamespace(id=type_id, name=name)


def _db(execute_results):
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    # Privacy check first, then the token-type bookkeeping statements.
    db.session.execute.side_effect = [_exec(fetchone=("FULL",)), *execute_results]
    return db


def _calls(db):
    return [call.args[1] for call in db.session.execute.call_args_list]


def test_known_types_are_one_lookup_and_one_usage_upsert():
    db = _db(
        [
            _exec(
                fetchall=[
                    _type_row(1, "prompt_tokens"),
                    _type_row(2, "completion_tokens"),
                    _type_row(3, "total_tokens"),
                ]
            ),
            _exec(),  # usage_tokens upsert
            _exec(),  # final UPDATE
        ]
    )

    db.set_response_payload(
        log_id=7,
        payload={"text": "ok"},
        usage={"prompt_tokens": 12, "completion_tokens": 300, "total_tokens": 312},
    )

    # privacy + token lookup + usage upsert + final UPDATE
    assert db.session.execute.call_count == 4
    assert db.session.commit.call_count == 1
    lookup, usage_params = _calls(db)[1], _calls(db)[2]
    assert lookup["names"] == ["prompt_tokens", "completion_tokens", "total_tokens"]
    assert usage_params["log_entry_id"] == 7
    assert {usage_params[f"type_id_{i}"] for i in range(3)} == {1, 2, 3}
    assert {usage_params[f"token_count_{i}"] for i in range(3)} == {12, 300, 312}


def test_missing_type_is_created_in_one_upsert():
    db = _db(
        [
            _exec(fetchall=[_type_row(1, "prompt_tokens")]),
            _exec(fetchall=[_type_row(4, "audio_milliseconds")]),  # creator insert
            _exec(),  # usage_tokens upsert
            _exec(),  # final UPDATE
        ]
    )

    db.set_response_payload(
        log_id=7,
        payload={"text": "ok"},
        usage={"prompt_tokens": 12, "audio_milliseconds": 8000},
    )

    assert db.session.execute.call_count == 5
    assert db.session.commit.call_count == 1
    create_params = _calls(db)[2]
    assert create_params["names"] == ["audio_milliseconds"]
    assert create_params["descriptions"] == [""]
    # The returned id feeds the usage upsert.
    assert _calls(db)[3]["type_id_1"] == 4


def test_concurrent_creator_winning_the_conflict_is_safe():
    """ON CONFLICT DO NOTHING returns nothing when a race created the type;
    the refetch must then find the row instead of crashing the request."""
    db = _db(
        [
            _exec(fetchall=[]),
            _exec(fetchall=[]),  # insert lost the race
            _exec(fetchall=[_type_row(9, "prompt_tokens")]),  # refetch
            _exec(),  # usage_tokens upsert
            _exec(),  # final UPDATE
        ]
    )

    db.set_response_payload(log_id=7, payload={"text": "ok"}, usage={"prompt_tokens": 5})

    assert db.session.execute.call_count == 6
    assert _calls(db)[3]["names"] == ["prompt_tokens"]
    assert _calls(db)[4]["type_id_0"] == 9


def test_zero_counts_still_register_the_type_but_write_no_usage_row():
    """Old behaviour: every usage name got a token type, only count > 0 got a
    usage_tokens row. The batch must keep that split."""
    db = _db(
        [
            _exec(fetchall=[_type_row(1, "prompt_tokens")]),
            _exec(fetchall=[_type_row(2, "completion_tokens")]),  # missing, zero count
            _exec(),  # usage_tokens upsert
            _exec(),  # final UPDATE
        ]
    )

    db.set_response_payload(log_id=7, payload={"text": "ok"}, usage={"prompt_tokens": 12, "completion_tokens": 0})

    # Both names registered…
    assert _calls(db)[1]["names"] == ["prompt_tokens", "completion_tokens"]
    assert _calls(db)[2]["names"] == ["completion_tokens"]
    # …but only the positive count reaches usage_tokens.
    usage_params = _calls(db)[3]
    assert usage_params["type_id_0"] == 1
    assert usage_params["token_count_0"] == 12
    assert "type_id_1" not in usage_params


def test_empty_usage_skips_all_token_bookkeeping():
    db = _db(
        [
            _exec(),  # final UPDATE only
        ]
    )

    db.set_response_payload(log_id=7, payload={"text": "ok"}, usage={})

    # privacy + final UPDATE — no token lookup, no upserts
    assert db.session.execute.call_count == 2
    assert db.session.commit.call_count == 1


def test_set_first_token_merges_into_the_final_update():
    for set_first_token in (True, False):
        db = _db(
            [
                _exec(),  # final UPDATE only
            ]
        )
        db.set_response_payload(log_id=7, payload={"text": "ok"}, set_first_token=set_first_token)

        final_params = _calls(db)[1]
        if set_first_token:
            assert final_params["first_token"] is not None
        else:
            assert final_params["first_token"] is None
