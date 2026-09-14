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
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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

    # The claim is a lease, not the settled_at stamp: a settlement that dies
    # before the ledger write must stay retryable, so the claim carries an
    # expiry and touches no settled column at all.
    params = _params_of(db.session.execute.call_args)
    assert params["id"] == 77
    assert params["lease"] == 1800

    # The client's own poll and the reconciler can both reach a finished batch;
    # the conditional UPDATE lets only one of them bill it.
    db.session.execute.return_value = MagicMock(rowcount=0)
    assert db.claim_batch_for_settlement(77) is False


def test_a_failed_settlement_is_released_for_a_retry():
    db = _db()
    db.release_batch_settlement(77)
    assert _params_of(db.session.execute.call_args) == {"id": 77}


def test_settling_a_batch_stamps_it_and_clears_the_lease():
    db = _db()
    db.mark_batch_settled(77)

    params = _params_of(db.session.execute.call_args)
    assert params["id"] == 77
    assert isinstance(params["now"], datetime.datetime)


def test_batch_usage_is_written_and_then_priced_by_the_shared_snapshot():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101, None), (102, None)])
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
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101, None)])
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
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101, None)])
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
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101, None)])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    db.record_batch_usage(
        [{"timestamp": _now(), "usage": {"prompt_tokens": 0, "completion_tokens": True, "total_tokens": 7}}]
    )

    usage_params = _params_of(db.session.execute.call_args_list[1])
    assert usage_params == {"log_0": 101, "type_0": 1, "count_0": 7}


def test_rows_are_written_in_chunks():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(101, None)])
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
        MagicMock(fetchall=lambda: [(101, None)]),
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


@pytest.mark.parametrize(
    ("team_id", "user_id", "api_key_id", "expected_params"),
    [
        # A team sees the team's objects.
        (12, 13, 11, {"kind": "batch", "team_id": 12, "limit": 100}),
        # A team-less key sees only its own user's objects — never the objects
        # of another unteamed user, which a "team_id IS NULL" scope would leak.
        (None, 13, 11, {"kind": "batch", "user_id": 13, "limit": 100}),
        # A key without a user falls back to the key itself.
        (None, None, 11, {"kind": "batch", "api_key_id": 11, "limit": 100}),
    ],
)
def test_listing_is_scoped_by_the_callers_principal(team_id, user_id, api_key_id, expected_params):
    db = _db()
    db.session.execute.return_value.mappings.return_value.all.return_value = []

    db.list_batch_objects_for_principal("batch", team_id, user_id, api_key_id)

    # Exactly one of the three scope parameters is bound — the one naming the
    # caller's principal — so the WHERE clause can only match that principal's rows.
    assert _params_of(db.session.execute.call_args) == expected_params


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


def test_usage_tokens_follow_the_request_id_not_the_insert_order():
    # A multi-row INSERT ... RETURNING does not promise its rows back in the
    # order they went in; the usage tokens must attach by request_id or one
    # line's tokens could be priced as another line's.
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(102, "b"), (101, "a")])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    db.record_batch_usage(
        [
            {"timestamp": _now(), "request_id": "a", "usage": {"total_tokens": 7}},
            {"timestamp": _now(), "request_id": "b", "usage": {"total_tokens": 3}},
        ]
    )

    calls = db.session.execute.call_args_list
    # Row "a" was returned second (id 101), row "b" first (id 102) — the usage
    # insert still puts 7 tokens on 101 and 3 on 102.
    usage_params = _params_of(calls[1])
    assert (usage_params["log_0"], usage_params["count_0"]) == (101, 7)
    assert (usage_params["log_1"], usage_params["count_1"]) == (102, 3)


def test_a_settlement_retry_skips_rows_the_ledger_already_holds():
    # The chunks commit before the batch is marked settled, so a settlement
    # retried after a partial commit re-inserts rows that are already booked.
    # They are skipped on the unique request_id, not an error: no second token
    # write, no snapshot over the old rows, and only the new rows are counted.
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(102, "batch-5-b")])
    db.add_token_type = lambda name, description="": ({"token-type-id": 1}, 200)

    written = db.record_batch_usage(
        [
            {"timestamp": _now(), "request_id": "batch-5-a", "usage": {"total_tokens": 7}},
            {"timestamp": _now(), "request_id": "batch-5-b", "usage": {"total_tokens": 3}},
        ]
    )

    assert written == 1
    calls = db.session.execute.call_args_list
    usage_params = _params_of(calls[1])
    assert (usage_params["log_0"], usage_params["count_0"]) == (102, 3)
    assert "log_1" not in usage_params
    assert _params_of(calls[2]) == {"log_ids": [102]}


def test_registering_a_file_keeps_the_models_it_names():
    db = _db()
    db.register_batch_object(
        kind="file",
        upstream_id="file-abc",
        provider_id=7,
        api_key_id=11,
        team_id=12,
        user_id=13,
        models=["gpt-4.1", "gpt-4o"],
    )

    params = _params_of(db.session.execute.call_args)
    assert json.loads(params["models"]) == ["gpt-4.1", "gpt-4o"]

    # A row that names no models stores NULL, and the upsert keeps what is
    # already there rather than blanking it.
    db.session.execute.reset_mock()
    db.register_batch_object(
        kind="batch", upstream_id="batch-abc", provider_id=7, api_key_id=11, team_id=12, user_id=13
    )
    assert _params_of(db.session.execute.call_args)["models"] is None


def test_a_registration_whose_id_another_provider_holds_is_refused():
    # A fresh insert and an upsert of the same provider's row each touch
    # exactly one row. A DO UPDATE that matches none means another provider
    # already holds the id: the registration must fail closed — so the caller
    # removes the provider object again — rather than overwrite or silently
    # skip.
    db = _db()
    db.session.execute.return_value = MagicMock(rowcount=0)
    with pytest.raises(RuntimeError, match="already held by another provider"):
        db.register_batch_object(
            kind="file", upstream_id="file-abc", provider_id=7, api_key_id=11, team_id=12, user_id=13
        )
    db.session.commit.assert_not_called()

    # The same-provider upsert commits as before.
    db.session.execute.return_value = MagicMock(rowcount=1)
    db.register_batch_object(kind="file", upstream_id="file-abc", provider_id=7, api_key_id=11, team_id=12, user_id=13)
    db.session.commit.assert_called_once()


def test_the_registration_conflict_target_matches_the_migrated_index():
    # The unique index on batch_objects is on a COALESCE *expression*, not the
    # bare columns, and PostgreSQL can only infer an expression index when the
    # ON CONFLICT target repeats the expression exactly. A bare-column target
    # does not match and the statement fails outright — which would turn every
    # provider upload into a 502. This keeps the two sides in lockstep; the
    # unit environment stubs the SQL away, so the migration file is the check.
    migration = (
        Path(dbmanager.__file__).parents[4]
        / "logos-webservice"
        / "src"
        / "main"
        / "resources"
        / "liquibase"
        / "changelog"
        / "031_batch_api.xml"
    )
    lines = migration.read_text(encoding="utf-8").splitlines()
    index_lines = [
        lines[index + 1]
        for index, line in enumerate(lines)
        if "CREATE" in line and "uq_batch_objects_upstream" in line and index + 1 < len(lines)
    ]
    assert len(index_lines) == 1
    assert "ON batch_objects(" in index_lines[0]
    expression = index_lines[0].split("ON batch_objects(", 1)[1].rstrip(");").strip()

    source = inspect.getsource(DBManager.register_batch_object)
    assert f"ON CONFLICT ({expression})" in source


def test_claiming_a_local_batch_stamps_the_runner_and_the_lease():
    db = _db()
    db.session.execute.return_value = MagicMock(rowcount=1)
    assert db.claim_local_batch(5, "runner-1", 600) is True

    params = _params_of(db.session.execute.call_args)
    assert params["id"] == 5
    assert params["runner"] == "runner-1"
    assert params["lease"] == 600
    assert isinstance(params["now"], datetime.datetime)

    # A live lease (or a terminal batch) leaves the update unmatched.
    db.session.execute.return_value = MagicMock(rowcount=0)
    assert db.claim_local_batch(5, "runner-1", 600) is False


def test_progress_updates_are_conditional_on_still_holding_the_batch():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchone=lambda: (True,))
    assert db.update_local_batch_progress(5, "runner-1", 3, 1, 600) is True

    params = _params_of(db.session.execute.call_args)
    assert (params["id"], params["runner"]) == (5, "runner-1")
    assert (params["completed"], params["failed"]) == (3, 1)

    # No cancel pending -> False; the row no longer belongs to this runner
    # (another one took it over after the lease lapsed) -> None, which the
    # runner treats as "stop, do not write an output file".
    db.session.execute.return_value = MagicMock(fetchone=lambda: (False,))
    assert db.update_local_batch_progress(5, "runner-1", 4, 1, 600) is False
    db.session.execute.return_value = MagicMock()
    db.session.execute.return_value.fetchone.return_value = None
    assert db.update_local_batch_progress(5, "runner-1", 4, 1, 600) is None


def test_finishing_a_local_batch_requires_still_holding_the_lease():
    db = _db()
    db.session.execute.return_value = MagicMock(rowcount=1)
    assert (
        db.finish_local_batch(5, "runner-1", status="completed", output_file_id="file-out", completed=9, failed=1)
        is True
    )

    params = _params_of(db.session.execute.call_args)
    assert (params["id"], params["runner"]) == (5, "runner-1")
    assert params["status"] == "completed"
    assert params["output_file_id"] == "file-out"
    assert (params["completed"], params["failed"]) == (9, 1)

    # A runner whose lease lapsed must not finalize the batch the new holder
    # is running.
    db.session.execute.return_value = MagicMock(rowcount=0)
    assert db.finish_local_batch(5, "runner-1", status="completed") is False


def test_line_checkpoints_are_upserted_per_line():
    db = _db()
    db.save_local_batch_lines(
        5,
        "runner-1",
        [
            {"custom_id": "q-1", "row": {"status_code": 200}},
            {"custom_id": "q-2", "row": {"status_code": 500}},
        ],
    )

    params = _params_of(db.session.execute.call_args)
    assert (params["id_0"], params["cid_0"]) == (5, "q-1")
    assert json.loads(params["row_0"]) == {"status_code": 200}
    assert (params["id_1"], params["cid_1"]) == (5, "q-2")
    # The update half is bound to the holder: a deposed runner's write must not
    # overwrite the new holder's rows for the same lines.
    assert params["runner"] == "runner-1"

    # Nothing finished -> nothing to write.
    db.session.execute.reset_mock()
    db.save_local_batch_lines(5, "runner-1", [])
    db.session.execute.assert_not_called()


def test_the_checkpoint_reads_back_by_custom_id():
    db = _db()
    db.session.execute.return_value.mappings.return_value.all.return_value = [
        {"custom_id": "q-1", "row": {"status_code": 200}},
        {"custom_id": "q-2", "row": {"status_code": 500}},
    ]

    assert db.get_local_batch_lines(5) == {
        "q-1": {"status_code": 200},
        "q-2": {"status_code": 500},
    }
    assert _params_of(db.session.execute.call_args) == {"id": 5}


def test_eligibility_rows_are_read_back_within_the_ttl():
    db = _db()
    db.session.execute.return_value = MagicMock(fetchall=lambda: [(25,), (26,)])

    assert db.get_batch_model_ineligibility(7) == {25, 26}

    params = _params_of(db.session.execute.call_args)
    assert params["pid"] == 7
    assert isinstance(params["now"], datetime.datetime)
    assert params["ttl"] == dbmanager.BATCH_MODEL_ELIGIBILITY_TTL_DAYS


def test_a_refusal_is_recorded_per_model_and_truncated():
    db = _db()
    db.record_model_batch_ineligibility(7, 25, "x" * 600)

    params = _params_of(db.session.execute.call_args)
    assert (params["pid"], params["mid"]) == (7, 25)
    assert len(params["detail"]) == 500
    assert isinstance(params["now"], datetime.datetime)


def test_a_provider_answer_syncs_the_fields_the_listing_cannot_render():
    # The listing is served from the ownership row, not from the provider, so
    # the result file and the running counts must be stored with the status.
    db = _db()
    db.record_batch_provider_state(
        "batch_1",
        {
            "status": "completed",
            "output_file_id": "file-out",
            "error_file_id": "file-err",
            # The shape the provider reports progress in: a nested object.
            "request_counts": {"total": 2, "completed": 1, "failed": 1},
        },
    )

    params = _params_of(db.session.execute.call_args)
    assert params["upstream_id"] == "batch_1"
    assert params["status"] == "completed"
    assert (params["output_file_id"], params["error_file_id"]) == ("file-out", "file-err")
    assert (params["total_requests"], params["completed_requests"], params["failed_requests"]) == (2, 1, 1)


def test_a_provider_answer_without_the_fields_binds_nulls_not_empty_values():
    # The statement's COALESCE is what keeps an earlier poll's result file
    # when a later answer omits it: the bound values are the nulls.
    db = _db()
    db.record_batch_provider_state("batch_1", {"status": "in_progress"})

    params = _params_of(db.session.execute.call_args)
    assert params["status"] == "in_progress"
    assert params["output_file_id"] is None
    assert params["error_file_id"] is None
    assert params["total_requests"] is None
    assert params["completed_requests"] is None
    assert params["failed_requests"] is None


def test_the_older_flat_count_fields_are_accepted_as_a_fallback():
    db = _db()
    db.record_batch_provider_state("batch_1", {"total_requests": 2, "completed_requests": 1, "failed_requests": 1})

    params = _params_of(db.session.execute.call_args)
    assert (params["total_requests"], params["completed_requests"], params["failed_requests"]) == (2, 1, 1)


def test_a_non_numeric_provider_count_is_not_bound_as_a_count():
    db = _db()
    db.record_batch_provider_state("batch_1", {"request_counts": {"total": "a lot", "completed": True}})

    params = _params_of(db.session.execute.call_args)
    assert params["total_requests"] is None
    assert params["completed_requests"] is None
