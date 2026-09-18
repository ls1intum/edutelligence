"""The settled-cost snapshot must never endanger the finalization write.

``update_log_entry_metrics`` writes the terminal ``result_status`` and then
snapshots ``settled_cost_micro_cents`` via ``logos_price_usage``. Pricing is the
riskier half (a function bug, a lock, a statement timeout), so it must run after
the status write is durably committed and its failure must be swallowed. The
snapshot is also recomputed on every finalization so a retry that corrects the
persisted usage rows corrects the stored cost.

The sync response path settles the snapshot on the queued payload write
(``store_response_payload(settle_cost=True)`` — #980 O14): the snapshot only
reads columns the billing commit made durable, so it prices after that commit
in its own transaction.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from logos import DBManager
from logos.dbutils import dbmanager


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


def _call_names(db):
    return [c[0] for c in db.session.mock_calls]


def test_pricing_failure_does_not_roll_back_the_success_status_write():
    db = _db()
    # First execute (the status UPDATE) succeeds; the second (the snapshot) fails.
    db.session.execute.side_effect = [MagicMock(), RuntimeError("logos_price_usage failed")]

    # The pricing failure must be contained, not propagated.
    db.update_log_entry_metrics(log_id=7, result_status="success")

    names = _call_names(db)
    assert names.count("execute") == 2
    assert "commit" in names[: names.index("execute", names.index("execute") + 1)]
    assert "rollback" in names  # the failed snapshot txn was rolled back


def test_status_write_is_committed_before_the_snapshot_is_attempted():
    db = _db()
    db.session.execute.side_effect = [MagicMock(), MagicMock()]

    db.update_log_entry_metrics(log_id=7, result_status="success")

    names = _call_names(db)
    second_execute = names.index("execute", names.index("execute") + 1)
    assert names.index("commit") < second_execute


def test_error_finalization_snapshots_its_measurable_delivered_cost():
    db = _db()
    db.session.execute.side_effect = [MagicMock(), MagicMock()]

    db.update_log_entry_metrics(log_id=7, result_status="error")

    assert _call_names(db).count("execute") == 2
    assert "le.result_status IN ('error', 'timeout')" in dbmanager._SETTLED_COST_SNAPSHOT_SQL
    assert "'billed_requests'" in dbmanager._SETTLED_COST_SNAPSHOT_SQL


def test_snapshot_sql_recomputes_and_carries_no_null_guard():
    # The guard `settled_cost_micro_cents IS NULL` would make a finalization retry
    # a no-op and freeze a cost snapshotted from partial usage.
    assert "settled_cost_micro_cents IS NULL" not in dbmanager._SETTLED_COST_SNAPSHOT_SQL
    assert "logos_price_usage" in dbmanager._SETTLED_COST_SNAPSHOT_SQL


def _privacy_row(level="FULL"):
    return MagicMock(fetchone=lambda: (level,))


def test_queued_payload_write_settles_the_cost_after_its_commit():
    db = _db()
    db.session.execute.side_effect = [
        _privacy_row(),  # privacy lookup
        MagicMock(),  # payload UPDATE
        MagicMock(),  # snapshot UPDATE
    ]

    db.store_response_payload(42, {"a": 1}, settle_cost=True)

    names = _call_names(db)
    assert names.count("execute") == 3
    payload_commit = names.index("commit")
    snapshot_execute = names.index("execute", payload_commit)
    assert snapshot_execute > payload_commit  # prices only what the billing/payload commit made durable
    assert "commit" in names[snapshot_execute + 1 :]  # the snapshot keeps its own commit


def test_payload_write_without_settle_cost_does_not_price():
    db = _db()
    db.session.execute.side_effect = [_privacy_row(), MagicMock()]

    db.store_response_payload(42, {"a": 1})

    assert _call_names(db).count("execute") == 2


def test_pricing_failure_in_queued_settle_keeps_the_payload_committed():
    db = _db()
    db.session.execute.side_effect = [
        _privacy_row(),
        MagicMock(),
        RuntimeError("logos_price_usage failed"),
    ]

    db.store_response_payload(42, {"a": 1}, settle_cost=True)  # must not raise

    names = _call_names(db)
    assert names.index("commit") < names.index("rollback")
