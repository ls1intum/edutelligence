"""The queries behind Batch API ownership and settlement.

Two properties are load-bearing and invisible from the HTTP tests: the
settlement latch is conditional, so a finished batch is billed once no matter
whether the client's poll or the reconciler gets there first, and a batch's
usage rows are priced by the same snapshot statement as every other request.

(The unit-test environment stubs SQLAlchemy, so ``text()`` yields no inspectable
statement — these assert on the bound parameters and the call structure.)
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from logos import DBManager
from logos.dbutils import dbmanager


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


def _params_of(call):
    return call.args[1] if len(call.args) > 1 else {}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def test_settlement_latch_reports_whether_this_caller_won_it():
    db = _db()
    db.session.execute.return_value = MagicMock(rowcount=1)
    assert db.claim_batch_for_settlement(77) is True

    # The client's own poll and the reconciler can both reach a finished batch;
    # the conditional UPDATE lets only one of them bill it.
    db.session.execute.return_value = MagicMock(rowcount=0)
    assert db.claim_batch_for_settlement(77) is False


def test_a_failed_settlement_is_released_for_a_retry():
    db = _db()
    db.release_batch_settlement(77)
    assert _params_of(db.session.execute.call_args) == {"id": 77}


def test_batch_usage_is_written_and_then_priced_by_the_shared_snapshot():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101,), (102,)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    written = db.record_batch_usage(
        [
            {"timestamp": _now(), "usage": {"prompt_tokens": 10}},
            {"timestamp": _now(), "usage": {"completion_tokens": 5}},
        ]
    )

    assert written == 2
    calls = db.session.execute.call_args_list
    assert len(calls) == 3  # log_entry rows, usage rows, cost snapshot
    # The snapshot runs over exactly the rows just written, through the same
    # statement an ordinary finalisation uses.
    assert _params_of(calls[2]) == {"log_ids": [101, 102]}


def test_batch_rows_default_to_the_batch_service_tier():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101,)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    db.record_batch_usage([{"timestamp": _now(), "usage": {}}])

    params = _params_of(db.session.execute.call_args_list[0])
    # 'batch' is what makes the price lookup pick the provider's batch rate;
    # without a batch rate it falls back to the standard one.
    assert params["tier_0"] == "batch"
    assert params["status_0"] == "success"
    assert params["privacy_0"] == "BILLING"


def test_an_owner_is_carried_onto_every_row():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101,)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    db.record_batch_usage(
        [
            {
                "timestamp": _now(),
                "api_key_id": 11,
                "team_id": 12,
                "user_id": 13,
                "provider_id": 7,
                "model_id": 25,
                "request_id": "custom-1",
                "usage": {},
            }
        ]
    )

    params = _params_of(db.session.execute.call_args_list[0])
    assert (params["aki_0"], params["tid_0"], params["uid_0"]) == (11, 12, 13)
    assert (params["pid_0"], params["mid_0"], params["rid_0"]) == (7, 25, "custom-1")


def test_zero_and_boolean_token_counts_are_not_billed():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101,)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    db.record_batch_usage(
        [{"timestamp": _now(), "usage": {"prompt_tokens": 0, "completion_tokens": True, "total_tokens": 7}}]
    )

    usage_params = _params_of(db.session.execute.call_args_list[1])
    assert usage_params == {"log_0": 101, "type_0": 1, "count_0": 7}


def test_rows_are_written_in_chunks():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101,)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    # A single batch can carry tens of thousands of results; they must not go
    # into one statement.
    written = db.record_batch_usage([{"timestamp": _now(), "usage": {"total_tokens": 1}}] * 3, chunk_size=1)

    assert written == 3
    assert len([c for c in db.session.execute.call_args_list if "log_ids" in _params_of(c)]) == 3


def test_no_rows_writes_nothing():
    db = _db()
    assert db.record_batch_usage([]) == 0
    db.session.execute.assert_not_called()


def test_a_snapshot_failure_does_not_lose_the_usage_rows():
    db = _db()
    db.session.execute.side_effect = [
        MagicMock(fetchall=lambda: [(101,)]),
        MagicMock(),
        RuntimeError("logos_price_usage failed"),
    ]
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    assert db.record_batch_usage([{"timestamp": _now(), "usage": {"total_tokens": 7}}]) == 1
    assert "rollback" in [c[0] for c in db.session.mock_calls]


def test_ownership_and_listing_queries_are_scoped():
    db = _db()
    db.session.execute.return_value.mappings.return_value.first.return_value = None
    db.session.execute.return_value.mappings.return_value.all.return_value = []

    # Keyed by the id alone: a caller supplies an id, not a provider, and the
    # row is what says whether the object lives at a provider or here.
    assert db.get_batch_object("file", "file-abc") is None
    assert _params_of(db.session.execute.call_args) == {"kind": "file", "upstream_id": "file-abc"}

    db.list_batch_objects_for_team(12, "batch")
    assert _params_of(db.session.execute.call_args) == {"kind": "batch", "team_id": 12, "limit": 100}


def test_capability_is_cached_per_provider_with_a_timestamp():
    db = _db()
    db.record_provider_batch_capability(7, False, "HTTP 404")

    params = _params_of(db.session.execute.call_args)
    assert params["pid"] == 7 and params["supports"] is False and params["detail"] == "HTTP 404"
    assert isinstance(params["now"], datetime.datetime)


def test_the_snapshot_statement_the_batch_path_reuses_is_the_shared_one():
    # Guards against the pricing being inlined a second time: both paths format
    # the same statement.
    assert "logos_price_usage" in dbmanager._SETTLED_COST_SNAPSHOT_SQL
    assert "{where_clause}" in dbmanager._SETTLED_COST_SNAPSHOT_SQL
