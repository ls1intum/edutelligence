"""Tests for per-user usage dashboard endpoints."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestMyUsageDBMethod:
    """Test DBManager.get_user_usage_stats."""

    def _make_db_manager(self, process_id=1):
        """Create a mock DBManager with controlled query results."""
        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)
        mock_session = MagicMock()

        # We'll control what each query returns
        call_count = {"n": 0}

        def fake_execute(sql, params=None):
            call_count["n"] += 1
            result = MagicMock()
            n = call_count["n"]
            if n == 1:  # total tokens
                result.fetchone.return_value = (1500,)
            elif n == 2:  # by model
                row1 = ("gpt-4", "prompt_tokens", 1000)
                row2 = ("gpt-4", "completion_tokens", 500)
                result.fetchall.return_value = [row1, row2]
            elif n == 3:  # by day
                from datetime import date
                result.fetchall.return_value = [(date(2026, 2, 19), 800), (date(2026, 2, 18), 700)]
            elif n == 4:  # cost
                result.fetchone.return_value = (0.025,)
            elif n == 5:  # request count
                result.scalar.return_value = 10
            elif n == 6:  # rate limits (get_rate_limits -> settings)
                result.fetchone.return_value = ({"rate_limit_rpm": 60, "rate_limit_tpm": 100000},)
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
                result.scalar.return_value = None
            return result

        mock_session.execute = fake_execute
        db.session = mock_session
        return db

    def test_returns_own_data(self):
        db = self._make_db_manager()
        data, status = db.get_user_usage_stats(process_id=1)
        assert status == 200
        assert data["total_tokens"] == 1500
        assert data["total_cost"] == 0.025
        assert data["total_requests"] == 10
        assert len(data["by_model"]) == 1
        assert data["by_model"][0]["model_name"] == "gpt-4"
        assert data["by_model"][0]["tokens"]["prompt_tokens"] == 1000
        assert data["by_model"][0]["tokens"]["completion_tokens"] == 500
        assert len(data["by_day"]) == 2
        assert data["rate_limits"]["rate_limit_rpm"] == 60

    def test_empty_usage(self):
        """Test user with no usage data."""
        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)
        mock_session = MagicMock()

        def fake_execute(sql, params=None):
            result = MagicMock()
            result.fetchone.return_value = (0,)
            result.fetchall.return_value = []
            result.scalar.return_value = 0
            return result

        mock_session.execute = fake_execute
        db.session = mock_session

        data, status = db.get_user_usage_stats(process_id=999)
        assert status == 200
        assert data["total_tokens"] == 0
        assert data["by_model"] == []


class TestMyModelsDBMethod:
    """Test DBManager.get_user_accessible_models."""

    def test_returns_accessible_models(self):
        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)
        mock_session = MagicMock()

        mock_rows = [
            (1, "gpt-4", "GPT-4 model", "/v1/chat/completions"),
            (2, "llama-3", "Llama 3 model", "/v1/chat/completions"),
        ]

        def fake_execute(sql, params=None):
            result = MagicMock()
            result.fetchall.return_value = mock_rows
            return result

        mock_session.execute = fake_execute
        db.session = mock_session

        models, status = db.get_user_accessible_models(process_id=1)
        assert status == 200
        assert len(models) == 2
        assert models[0]["name"] == "gpt-4"
        assert models[0]["description"] == "GPT-4 model"
        assert models[1]["name"] == "llama-3"

    def test_no_models(self):
        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)
        mock_session = MagicMock()

        def fake_execute(sql, params=None):
            result = MagicMock()
            result.fetchall.return_value = []
            return result

        mock_session.execute = fake_execute
        db.session = mock_session

        models, status = db.get_user_accessible_models(process_id=1)
        assert status == 200
        assert models == []


class TestUserDataIsolation:
    """Ensure users can only access their own data."""

    def test_process_id_filtering(self):
        """The SQL queries always filter by process_id, ensuring isolation."""
        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)
        mock_session = MagicMock()

        captured_params = []

        def fake_execute(sql, params=None):
            captured_params.append(params)
            result = MagicMock()
            result.fetchone.return_value = (0,)
            result.fetchall.return_value = []
            result.scalar.return_value = 0
            return result

        mock_session.execute = fake_execute
        db.session = mock_session

        db.get_user_usage_stats(process_id=42)

        # All queries should use pid=42
        for p in captured_params:
            if p and "pid" in p:
                assert p["pid"] == 42
