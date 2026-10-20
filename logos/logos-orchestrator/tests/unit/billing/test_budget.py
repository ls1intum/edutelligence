"""Unit tests for logos.billing.budget.check_monthly_budget provider overrides."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from logos.billing.budget import check_monthly_budget


class _FakeDb:
    def __init__(self):
        self.team = {"team_monthly_budget_micro_cents": 100}
        self.provider_override = (False, None)
        self.default_used = 0
        self.provider_used = 0
        self.team_used = 0
        self.key_limit = None
        self.key_used = 0

    def get_team(self, team_id):
        return self.team

    def get_team_budget_usage(self, team_id, month_start):
        return self.team_used

    def get_team_default_budget_usage(self, team_id, month_start):
        return self.default_used

    def get_team_provider_budget(self, team_id, provider_id):
        return self.provider_override

    def get_team_provider_budget_usage(self, team_id, provider_id, month_start):
        return self.provider_used

    def get_api_key_budget_limit(self, api_key_id):
        return self.key_limit

    def get_api_key_budget_usage(self, api_key_id, month_start):
        return self.key_used


def _auth(**kwargs):
    base = dict(api_key_id=1, team_id=7, key_type="developer")
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_local_provider_skips_budget():
    db = _FakeDb()
    db.team_used = 999
    check_monthly_budget(db, _auth(), False, "2026-10-01")


def test_default_bucket_rejects_when_over():
    db = _FakeDb()
    db.default_used = 100
    with pytest.raises(HTTPException) as exc:
        check_monthly_budget(db, _auth(), True, "2026-10-01", provider_id=3)
    assert exc.value.status_code == 402
    assert "Team monthly budget exceeded" in exc.value.detail


def test_sponsored_provider_unlimited_skips_default_bucket():
    db = _FakeDb()
    db.default_used = 100
    db.provider_override = (True, None)
    check_monthly_budget(db, _auth(), True, "2026-10-01", provider_id=3)


def test_provider_override_cap_rejects():
    db = _FakeDb()
    db.provider_override = (True, 50)
    db.provider_used = 50
    with pytest.raises(HTTPException) as exc:
        check_monthly_budget(db, _auth(), True, "2026-10-01", provider_id=3)
    assert exc.value.status_code == 402
    assert "for this provider" in exc.value.detail


def test_application_key_ignores_provider_override():
    db = _FakeDb()
    db.key_limit = 10
    db.key_used = 10
    db.provider_override = (True, None)
    with pytest.raises(HTTPException) as exc:
        check_monthly_budget(db, _auth(key_type="application"), True, "2026-10-01", provider_id=3)
    assert "Application monthly budget exceeded" in exc.value.detail


def test_provider_override_zero_cap_rejects():
    db = _FakeDb()
    db.provider_override = (True, 0)
    with pytest.raises(HTTPException) as exc:
        check_monthly_budget(db, _auth(), True, "2026-10-01", provider_id=3)
    assert exc.value.status_code == 402
    assert "for this provider" in exc.value.detail


def test_without_team_check_only_the_key_budget_applies():
    db = _FakeDb()
    db.team_used = 100
    check_monthly_budget(db, _auth(), True, "2026-10-01", check_team=False)

    db.key_limit = 10
    db.key_used = 10
    with pytest.raises(HTTPException) as exc:
        check_monthly_budget(db, _auth(), True, "2026-10-01", check_team=False)
    assert "Personal monthly budget exceeded" in exc.value.detail
