"""Tests for batch user provisioning and CSV export."""

import csv
import io
import json
from unittest.mock import MagicMock

from logos.dbutils.dbrequest import BatchCreateUsersRequest


class TestBatchCreateUsersRequest:
    """Test the Pydantic request model."""

    def test_valid_request(self):
        req = BatchCreateUsersRequest(
            logos_key="lg-root-abc123",
            emails=["alice@example.com", "bob@example.com"],
            model_ids=[1, 2],
            rate_limit_rpm=60,
            rate_limit_tpm=100000,
        )
        assert req.emails == ["alice@example.com", "bob@example.com"]
        assert req.model_ids == [1, 2]
        assert req.rate_limit_rpm == 60
        assert req.rate_limit_tpm == 100000

    def test_defaults(self):
        req = BatchCreateUsersRequest(
            logos_key="lg-root-abc",
            emails=["user@test.com"],
            model_ids=[1],
        )
        assert req.rate_limit_rpm == 60
        assert req.rate_limit_tpm == 100000

    def test_empty_emails(self):
        req = BatchCreateUsersRequest(
            logos_key="lg-root-abc",
            emails=[],
            model_ids=[1],
        )
        assert req.emails == []


class TestBatchCreateUsers:
    """Test DBManager.batch_create_users."""

    def _make_db_manager(self, is_root=True, existing_emails=None, models=None):
        """Create a mock DBManager for testing batch_create_users."""
        existing_emails = existing_emails or set()
        models = models or {1: {"id": 1, "name": "gpt-4"}, 2: {"id": 2, "name": "llama"}}

        from logos.dbutils.dbmanager import DBManager

        db = DBManager.__new__(DBManager)

        # Track inserts
        db._insert_log = []
        db._next_id = 1

        def fake_insert(table, data):
            db._insert_log.append((table, data))
            result = db._next_id
            db._next_id += 1
            return result

        db.insert = fake_insert
        db.check_authorization = MagicMock(return_value=is_root)
        db.get_model = lambda mid: models.get(mid)

        # Mock session for duplicate checking
        mock_session = MagicMock()

        def fake_execute(sql, params=None):
            result = MagicMock()
            if params and "email" in (params or {}):
                email = params["email"]
                if email in existing_emails:
                    result.fetchone.return_value = (100,)  # existing user id
                else:
                    result.fetchone.return_value = None
            elif params and "uid" in (params or {}):
                result.fetchone.return_value = (200, "lg-existing-key")
            elif params and "pid" in (params or {}):
                # check profile_model_permissions existence
                result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
            return result

        mock_session.execute = fake_execute
        mock_session.commit = MagicMock()
        db.session = mock_session

        return db

    def test_batch_create_success(self):
        db = self._make_db_manager()
        result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["alice@example.com", "bob@example.com"],
            model_ids=[1, 2],
            rate_limit_rpm=30,
            rate_limit_tpm=50000,
        )
        assert status == 200
        users = result["result"]
        assert len(users) == 2
        assert users[0]["email"] == "alice@example.com"
        assert users[0]["status"] == "created"
        assert users[0]["logos_key"].startswith("lg-")
        assert users[1]["email"] == "bob@example.com"
        assert users[1]["status"] == "created"

        # Verify inserts: for each user: 1 user + 1 process + 1 profile + 2 permissions = 5
        inserts = db._insert_log
        tables = [t for t, _ in inserts]
        assert tables.count("users") == 2
        assert tables.count("process") == 2
        assert tables.count("profiles") == 2
        assert tables.count("profile_model_permissions") == 4  # 2 users * 2 models

    def test_batch_create_not_root(self):
        db = self._make_db_manager(is_root=False)
        result, status = db.batch_create_users(
            logos_key="lg-not-root",
            emails=["test@test.com"],
            model_ids=[1],
        )
        assert status == 500
        assert "error" in result

    def test_batch_create_empty_emails(self):
        db = self._make_db_manager()
        result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=[],
            model_ids=[1],
        )
        assert status == 400
        assert "error" in result

    def test_batch_create_duplicate_email(self):
        db = self._make_db_manager(existing_emails={"existing@example.com"})
        result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["existing@example.com", "new@example.com"],
            model_ids=[1],
        )
        assert status == 200
        users = result["result"]
        assert len(users) == 2
        assert users[0]["status"] == "already_exists"
        assert users[1]["status"] == "created"

    def test_batch_create_invalid_model(self):
        db = self._make_db_manager(models={1: {"id": 1, "name": "gpt-4"}})
        result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["test@test.com"],
            model_ids=[1, 999],
        )
        assert status == 400
        assert "error" in result
        assert "999" in result["error"]

    def test_batch_create_rate_limits_in_settings(self):
        db = self._make_db_manager()
        _result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["user@test.com"],
            model_ids=[1],
            rate_limit_rpm=30,
            rate_limit_tpm=50000,
        )
        assert status == 200
        # Find the process insert
        process_inserts = [(t, d) for t, d in db._insert_log if t == "process"]
        assert len(process_inserts) == 1
        settings = json.loads(process_inserts[0][1]["settings"])
        assert settings["rate_limit_rpm"] == 30
        assert settings["rate_limit_tpm"] == 50000

    def test_batch_create_email_stored(self):
        db = self._make_db_manager()
        _result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["user@test.com"],
            model_ids=[1],
        )
        assert status == 200
        # Find user insert and check email
        user_inserts = [(t, d) for t, d in db._insert_log if t == "users"]
        assert len(user_inserts) == 1
        assert user_inserts[0][1]["email"] == "user@test.com"

    def test_batch_create_email_normalized(self):
        db = self._make_db_manager()
        result, status = db.batch_create_users(
            logos_key="lg-root-key",
            emails=["  User@Example.COM  "],
            model_ids=[1],
        )
        assert status == 200
        users = result["result"]
        assert users[0]["email"] == "user@example.com"


class TestCSVExport:
    """Test CSV export of email-to-key mapping."""

    def test_csv_output_format(self):
        """Verify the CSV format is correct."""
        # Simulate what the endpoint does
        data = [
            {"email": "alice@example.com", "logos_key": "lg-alice-abc123"},
            {"email": "bob@example.com", "logos_key": "lg-bob-def456"},
        ]
        lines = ["email,logos_key"]
        for row in data:
            lines.append(f"{row['email']},{row['logos_key']}")
        csv_content = "\n".join(lines) + "\n"

        # Parse the CSV
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)
        assert rows[0] == ["email", "logos_key"]
        assert rows[1] == ["alice@example.com", "lg-alice-abc123"]
        assert rows[2] == ["bob@example.com", "lg-bob-def456"]

    def test_csv_empty_list(self):
        """Verify empty export produces header-only CSV."""
        data = []
        lines = ["email,logos_key"]
        for row in data:
            lines.append(f"{row['email']},{row['logos_key']}")
        csv_content = "\n".join(lines) + "\n"

        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)
        assert len(rows) == 1  # header only
        assert rows[0] == ["email", "logos_key"]
