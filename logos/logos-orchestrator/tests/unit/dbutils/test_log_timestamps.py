"""Request arrival timestamps survive deferred log persistence."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from logos.dbutils.dbmanager import DBManager


@pytest.mark.parametrize("deferred", [False, True])
def test_log_insert_uses_the_supplied_arrival_time(deferred):
    arrival = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    db.session.execute.return_value.first.return_value = None
    db.session.execute.return_value.fetchone.return_value = SimpleNamespace(id=99)
    write = db.ensure_log_usage if deferred else db.log_usage

    write(
        api_key_id=1,
        team_id=None,
        user_id=None,
        environment=None,
        log_level="BILLING",
        request_id="req-arrival",
        timestamp_request=arrival,
    )

    params = db.session.execute.call_args.args[1]
    assert datetime.datetime.fromisoformat(params["ts"]) == arrival


def test_log_insert_without_arrival_defaults_to_current_time():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    before = datetime.datetime.now(datetime.timezone.utc)
    db.log_usage(api_key_id=1, team_id=None, user_id=None, environment=None, log_level="BILLING")
    after = datetime.datetime.now(datetime.timezone.utc)

    params = db.session.execute.call_args.args[1]
    assert before <= datetime.datetime.fromisoformat(params["ts"]) <= after
