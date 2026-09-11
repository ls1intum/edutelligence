"""The OpenAI Batch API, served by forwarding to a provider that has one.

Logos hands the job to the provider's batch endpoint — that is where the
provider's batch rate applies — and keeps the three things a proxy exists for:
the key's model permissions are enforced on every request line of the input
file, the ids the provider mints are owned by the team that created them, and a
finished batch's usage is booked into the same ledger as everything else.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import logos as main
from logos import batch_api, batch_local
from logos.batch_api import (
    BATCH_PROVIDER_HEADER,
    BatchOperation,
    batch_operation_url,
    batch_provider_headers,
    parse_batch_api_path,
    reconcile_batches_once,
    resolve_batch_provider,
    settle_batch,
    validate_and_rewrite_batch_input,
)
from logos.request_content import is_batch_api_path

OPENAI_PROVIDER = {
    "id": 7,
    "name": "openai",
    "base_url": "https://api.openai.com/v1",
    "cloud_provider_type": "openai",
    "auth_name": "Authorization",
    "auth_format": "Bearer {}",
    "api_key": "sk-test",
    "supports_batch": True,
    "capability_checked_at": datetime.now(timezone.utc),
}

AZURE_PROVIDER = {
    "id": 8,
    "name": "azure",
    "base_url": "https://res.openai.azure.com/openai/deployments/",
    "cloud_provider_type": "azure",
    "auth_name": "api-key",
    "auth_format": "{}",
    "api_key": "az-key",
    "supports_batch": True,
    "capability_checked_at": datetime.now(timezone.utc),
}

# What the key may run, as get_batch_model_deployments returns it.
OPENAI_DEPLOYMENTS = [
    {
        "model_id": 25,
        "model_name": "gpt-4.1",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "provider_id": 7,
        "provider_type": "cloud",
        "cloud_provider_type": "openai",
    },
]
AZURE_DEPLOYMENTS = [
    {
        "model_id": 25,
        "model_name": "gpt-4.1",
        "endpoint": (
            "https://res.openai.azure.com/openai/deployments/gpt-41/chat/completions?api-version=2025-01-01-preview"
        ),
        "provider_id": 8,
        "provider_type": "cloud",
        "cloud_provider_type": "azure",
    },
]

# A model only a worker node serves: no provider Batch API can run it, so a
# batch that names it is executed by Logos itself.
LOCAL_DEPLOYMENTS = [
    {
        "model_id": 40,
        "model_name": "qwen3-32b",
        "endpoint": None,
        "provider_id": 15,
        "provider_type": "logosnode",
        "cloud_provider_type": None,
    },
]

client = TestClient(main.app, raise_server_exceptions=False)

OWN_TEAM = 12
OTHER_TEAM = 99


def _auth(api_key_id=11, team_id=OWN_TEAM):
    return SimpleNamespace(
        key_value="lg-test",
        api_key_id=api_key_id,
        api_key_name="test-key",
        key_type="user",
        team_id=team_id,
        user_id=13,
        environment="test",
        log_level="BILLING",
        settings={},
        default_priority=0,
    )


def _remote(object_id, team_id, **extra):
    """An ownership row for an object that lives at the provider."""
    return {
        "id": object_id,
        "team_id": team_id,
        "provider_id": 7,
        "execution": "provider",
        "settled_at": None,
        "created_at": datetime.now(timezone.utc),
        **extra,
    }


def _line(custom_id="one", model="gpt-4.1", url="/v1/chat/completions", body=None):
    payload = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    return {"custom_id": custom_id, "method": "POST", "url": url, "body": body if body is not None else payload}


def _jsonl(*lines):
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode()


# ---------------------------------------------------------------------------
# is_batch_api_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "v1/batches",
        "v1/batches/batch_123",
        "v1/batches/batch_123/cancel",
        "v1/files",
        "v1/files/file_123",
        "v1/files/file_123/content",
        "/v1/batches",
        "openai/batches",
        "openai/files",
        "openai/v1/batches",
        "openai/v1/files/file_123/content",
        "jobs/v1/batches",
        "jobs/v1/files",
        "jobs/openai/v1/batches",
    ],
)
def test_is_batch_api_path_recognises_batch_operations(path):
    assert is_batch_api_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "v1/chat/completions",
        "v1/completions",
        "v1/embeddings",
        "v1/responses",
        "v1/audio/transcriptions",
        "v1/models",
        "v1/files_backup",
        "v1/mybatches",
        "v1/batch",
        # The v2 (Cohere) mirror has no batch routes.
        "v2/batches",
        "v2/files",
        "jobs/v2/batches",
        "v2/embed",
        "pooling",
        "",
        None,
    ],
)
def test_is_batch_api_path_ignores_regular_operations(path):
    assert not is_batch_api_path(path)


# ---------------------------------------------------------------------------
# parse_batch_api_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("v1/files", "POST", ("files", None, None, True)),
        ("v1/files", "GET", ("files", None, None, False)),
        ("v1/files/file_1", "GET", ("files", "file_1", None, False)),
        ("v1/files/file_1", "DELETE", ("files", "file_1", None, False)),
        ("v1/files/file_1/content", "GET", ("files", "file_1", "content", False)),
        ("v1/batches", "POST", ("batches", None, None, False)),
        ("v1/batches", "GET", ("batches", None, None, False)),
        ("v1/batches/batch_1", "GET", ("batches", "batch_1", None, False)),
        ("v1/batches/batch_1/cancel", "POST", ("batches", "batch_1", "cancel", False)),
        ("openai/v1/files/file_1/content", "GET", ("files", "file_1", "content", False)),
        ("jobs/v1/batches/batch_1/cancel", "POST", ("batches", "batch_1", "cancel", False)),
        ("jobs/openai/v1/files", "POST", ("files", None, None, True)),
    ],
)
def test_parse_batch_api_path_recovers_the_operation(path, method, expected):
    op = parse_batch_api_path(path, method=method)
    assert op is not None
    resource, resource_id, suboperation, is_upload = expected
    assert (op.resource, op.resource_id, op.suboperation, op.is_file_upload) == (
        resource,
        resource_id,
        suboperation,
        is_upload,
    )


@pytest.mark.parametrize(
    "path",
    [
        "v1/batches/batch_1/unknown",
        "v1/files/file_1/unknown",
        "v1/batches/batch_1/cancel/extra",
        "v1/batch",
        "v1/chat/completions",
        "",
        None,
    ],
)
def test_parse_batch_api_path_rejects_non_batch_shapes(path):
    assert parse_batch_api_path(path) is None


def test_mirrored_paths_are_normalised_to_the_canonical_version():
    # The mirrors are inbound spellings only; a provider whose base_url has no
    # version segment must still be addressed at /v1/....
    for path in ("openai/files", "jobs/openai/files", "openai/v1/files", "jobs/v1/files"):
        assert parse_batch_api_path(path, method="POST").path == "v1/files"


# ---------------------------------------------------------------------------
# Upstream URL and header construction
# ---------------------------------------------------------------------------


def test_generic_provider_url_dedups_the_version_prefix():
    op = parse_batch_api_path("v1/files/file_1/content", method="GET")
    assert batch_operation_url(OPENAI_PROVIDER, op) == "https://api.openai.com/v1/files/file_1/content"


def test_generic_provider_url_keeps_the_version_when_the_base_lacks_it():
    provider = {**OPENAI_PROVIDER, "base_url": "https://proxy.example.com"}
    for path in ("v1/batches/batch_1/cancel", "openai/batches/batch_1/cancel", "jobs/openai/batches/batch_1/cancel"):
        op = parse_batch_api_path(path, method="POST")
        assert batch_operation_url(provider, op) == "https://proxy.example.com/v1/batches/batch_1/cancel"


def test_generic_provider_url_forwards_the_query_verbatim():
    op = parse_batch_api_path("v1/batches", method="GET", query="after=batch_1&limit=5")
    assert batch_operation_url(OPENAI_PROVIDER, op) == "https://api.openai.com/v1/batches?after=batch_1&limit=5"


def test_provider_without_a_base_url_is_a_502():
    provider = {**OPENAI_PROVIDER, "base_url": "  "}
    with pytest.raises(HTTPException) as exc:
        batch_operation_url(provider, parse_batch_api_path("v1/batches", method="POST"))
    assert exc.value.status_code == 502


def test_azure_batch_is_addressed_on_the_v1_surface():
    # Verified against a live resource: the dated data-plane version that first
    # served /openai/batches is long gone (2024-02-01 answers 404), while the
    # /openai/v1 surface serves them and carries the newer models.
    op = parse_batch_api_path("v1/batches", method="POST")
    assert batch_operation_url(AZURE_PROVIDER, op) == "https://res.openai.azure.com/openai/v1/batches"


def test_azure_batch_query_is_forwarded():
    op = parse_batch_api_path("v1/batches", method="GET", query="limit=5")
    assert batch_operation_url(AZURE_PROVIDER, op) == "https://res.openai.azure.com/openai/v1/batches?limit=5"


def test_azure_batch_api_version_override_uses_the_dated_route(monkeypatch):
    monkeypatch.setattr(batch_api, "AZURE_BATCH_API_VERSION", "2024-10-21")
    op = parse_batch_api_path("v1/files/file_1/content", method="GET")
    assert batch_operation_url(AZURE_PROVIDER, op) == (
        "https://res.openai.azure.com/openai/files/file_1/content?api-version=2024-10-21"
    )


def test_azure_batch_api_version_override_keeps_a_client_supplied_version(monkeypatch):
    monkeypatch.setattr(batch_api, "AZURE_BATCH_API_VERSION", "2024-10-21")
    op = parse_batch_api_path("v1/batches", method="GET", query="api-version=2025-04-01-preview")
    assert batch_operation_url(AZURE_PROVIDER, op) == (
        "https://res.openai.azure.com/openai/batches?api-version=2025-04-01-preview"
    )


def test_azure_provider_uses_the_resource_api_key_header():
    assert batch_provider_headers(AZURE_PROVIDER) == {"api-key": "az-key"}


def test_azure_provider_without_a_key_is_a_502():
    with pytest.raises(HTTPException) as exc:
        batch_provider_headers({**AZURE_PROVIDER, "api_key": None})
    assert exc.value.status_code == 502


def test_generic_provider_uses_its_stored_auth_format():
    assert batch_provider_headers(OPENAI_PROVIDER) == {"Authorization": "Bearer sk-test"}


def test_keyless_upstream_gets_no_auth_header():
    assert batch_provider_headers({**OPENAI_PROVIDER, "api_key": None}) == {}


# ---------------------------------------------------------------------------
# Provider resolution and capability
# ---------------------------------------------------------------------------


class _ResolvingDB:
    def __init__(self, providers):
        self.providers = providers
        self.recorded = []

    def get_batch_provider_candidates(self, api_key_id):
        return list(self.providers)

    def record_provider_batch_capability(self, provider_id, supports, detail=""):
        self.recorded.append((provider_id, supports, detail))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_resolution_without_candidates_keeps_the_501():
    with pytest.raises(HTTPException) as exc:
        await resolve_batch_provider(_auth(), {}, _ResolvingDB([]))
    assert exc.value.status_code == 501
    assert exc.value.detail["error"]["code"] == "batch_api_not_supported"


@pytest.mark.asyncio
async def test_single_candidate_is_selected_implicitly():
    assert await resolve_batch_provider(_auth(), {}, _ResolvingDB([AZURE_PROVIDER])) is AZURE_PROVIDER


@pytest.mark.asyncio
async def test_multiple_candidates_require_the_provider_header():
    with pytest.raises(HTTPException) as exc:
        await resolve_batch_provider(_auth(), {}, _ResolvingDB([OPENAI_PROVIDER, AZURE_PROVIDER]))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "multiple_batch_providers"


@pytest.mark.asyncio
async def test_provider_header_is_read_case_insensitively():
    # Starlette lowercases header names, so a case-sensitive lookup would make
    # explicit selection impossible over HTTP while passing a dict-based test.
    db = _ResolvingDB([OPENAI_PROVIDER, AZURE_PROVIDER])
    for spelling in (BATCH_PROVIDER_HEADER, BATCH_PROVIDER_HEADER.lower(), BATCH_PROVIDER_HEADER.upper()):
        assert await resolve_batch_provider(_auth(), {spelling: "openai"}, db) is OPENAI_PROVIDER
    assert await resolve_batch_provider(_auth(), {"x-logos-provider": "8"}, db) is AZURE_PROVIDER


@pytest.mark.asyncio
async def test_header_naming_an_unauthorized_provider_is_a_403():
    with pytest.raises(HTTPException) as exc:
        await resolve_batch_provider(_auth(), {"x-logos-provider": "elsewhere"}, _ResolvingDB([OPENAI_PROVIDER]))
    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "batch_provider_not_authorized"


@pytest.mark.asyncio
async def test_a_provider_without_a_batch_api_is_not_a_candidate(monkeypatch):
    # A self-hosted OpenAI-shaped inference endpoint serves chat and nothing
    # else. Counting it as a batch target would make the choice ambiguous for
    # every key that may also use it, and send jobs where they 404.
    inference_only = {
        **OPENAI_PROVIDER,
        "id": 26,
        "name": "morpheus",
        "base_url": "https://morpheus.example.com/api/v1",
        "supports_batch": None,
        "capability_checked_at": None,
    }
    db = _ResolvingDB([AZURE_PROVIDER, inference_only])
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)

    def probe(request):
        assert "morpheus" in str(request.url)
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(probe)))

    assert await resolve_batch_provider(_auth(), {}, db) is AZURE_PROVIDER
    assert db.recorded == [(26, False, "HTTP 404")]


@pytest.mark.asyncio
async def test_a_stale_capability_is_reprobed(monkeypatch):
    stale = {
        **OPENAI_PROVIDER,
        "supports_batch": False,
        "capability_checked_at": datetime.now(timezone.utc) - timedelta(days=30),
    }
    db = _ResolvingDB([stale])
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(
        batch_api,
        "_http_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
        ),
    )

    assert await resolve_batch_provider(_auth(), {}, db) is stale
    assert db.recorded == [(7, True, "")]


# ---------------------------------------------------------------------------
# Input file validation
# ---------------------------------------------------------------------------


def test_a_permitted_model_is_rewritten_to_the_azure_deployment():
    content, counts = validate_and_rewrite_batch_input(_jsonl(_line()), AZURE_PROVIDER, AZURE_DEPLOYMENTS)
    line = json.loads(content.splitlines()[0])
    assert line["body"]["model"] == "gpt-41"
    assert line["url"] == "/chat/completions"
    assert counts == {25: 1}


def test_a_generic_provider_keeps_the_model_and_versioned_url():
    content, counts = validate_and_rewrite_batch_input(_jsonl(_line()), OPENAI_PROVIDER, OPENAI_DEPLOYMENTS)
    line = json.loads(content.splitlines()[0])
    assert line["body"]["model"] == "gpt-4.1"
    assert line["url"] == "/v1/chat/completions"
    assert counts == {25: 1}


def test_a_model_the_key_may_not_use_is_refused():
    # Provider permission alone does not authorise what the batch runs: each
    # line picks its own model, and the shared upstream credential would run it.
    with pytest.raises(HTTPException) as exc:
        validate_and_rewrite_batch_input(_jsonl(_line(model="gpt-5.6-luna")), AZURE_PROVIDER, AZURE_DEPLOYMENTS)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "model_not_permitted"
    assert "gpt-5.6-luna" in exc.value.detail["error"]["message"]


def test_an_unsupported_request_endpoint_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_and_rewrite_batch_input(_jsonl(_line(url="/v1/files")), OPENAI_PROVIDER, OPENAI_DEPLOYMENTS)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "unsupported_batch_endpoint"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"not json\n", "invalid_batch_line"),
        (b'["a list"]\n', "invalid_batch_line"),
        (b'{"method": "POST", "url": "/v1/chat/completions", "body": {"model": "gpt-4.1"}}\n', "invalid_batch_line"),
        (b'{"custom_id": "a", "url": "/v1/chat/completions"}\n', "invalid_batch_line"),
        (b"\n \n", "empty_batch_file"),
    ],
)
def test_malformed_request_lines_are_refused(content, code):
    with pytest.raises(HTTPException) as exc:
        validate_and_rewrite_batch_input(content, OPENAI_PROVIDER, OPENAI_DEPLOYMENTS)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == code


def test_a_repeated_custom_id_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_and_rewrite_batch_input(_jsonl(_line("same"), _line("same")), OPENAI_PROVIDER, OPENAI_DEPLOYMENTS)
    assert exc.value.status_code == 400
    assert "same" in exc.value.detail["error"]["message"]


def test_too_many_request_lines_are_refused(monkeypatch):
    monkeypatch.setattr(batch_api, "MAX_BATCH_REQUESTS", 2)
    with pytest.raises(HTTPException) as exc:
        validate_and_rewrite_batch_input(
            _jsonl(_line("a"), _line("b"), _line("c")), OPENAI_PROVIDER, OPENAI_DEPLOYMENTS
        )
    assert exc.value.detail["error"]["code"] == "batch_file_too_many_requests"


# ---------------------------------------------------------------------------
# End-to-end forward through the app
# ---------------------------------------------------------------------------


class _FakeDB:
    """One fake DBManager shared by every ``with DBManager()`` in a request."""

    def __init__(self, providers, deployments, owned=None, budget_error=None):
        self.providers = providers
        self.deployments = deployments
        self.owned = dict(owned or {})
        self.budget_error = budget_error
        # The registration retries run on the shared session: without a
        # rollback between attempts the second attempt would raise
        # PendingRollbackError instead of retrying, so the retry path touches
        # it and the tests can see that it happened.
        self.session = MagicMock()
        self.registered = []
        self.status_updates = []
        self.stored_files = {}
        self.local_batches = {}
        self.deleted = []
        self.cancelled = []
        self.log_usage_kwargs = None
        self.finalization = None
        self.ineligible = {}
        self.eligibility_records = []
        self.fail_registration = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # resolution
    def get_batch_provider_candidates(self, api_key_id):
        return list(self.providers)

    def record_provider_batch_capability(self, provider_id, supports, detail=""):
        pass

    def get_batch_provider(self, provider_id):
        return next((p for p in self.providers if int(p["id"]) == int(provider_id)), None)

    def get_batch_model_deployments(self, api_key_id, provider_id=None):
        rows = list(self.deployments)
        if provider_id is None:
            return rows
        return [row for row in rows if int(row["provider_id"]) == int(provider_id)]

    # ownership
    def get_batch_object(self, kind, upstream_id):
        return self.owned.get((kind, upstream_id))

    def register_batch_object(self, **kwargs):
        # True fails every registration; a kind fails only that one, so a test
        # can keep the file row while breaking the batch row.
        if self.fail_registration and self.fail_registration in (True, kwargs.get("kind")):
            raise RuntimeError("the database is down")
        self.registered.append(kwargs)
        self.owned[(kwargs["kind"], kwargs["upstream_id"])] = {
            "id": 1,
            "team_id": kwargs["team_id"],
            "settled_at": None,
            "execution": "provider",
            **kwargs,
        }

    def list_batch_objects_for_principal(self, kind, team_id, user_id, api_key_id, limit=100):
        rows = []
        for key, row in self.owned.items():
            if key[0] != kind:
                continue
            if team_id is not None:
                matches = row.get("team_id") == team_id
            elif user_id is not None:
                # A team-less key sees only its own user's objects — the same
                # predicate the database query uses.
                matches = row.get("team_id") is None and row.get("user_id") == user_id
            else:
                matches = row.get("api_key_id") == api_key_id
            if matches:
                rows.append(row)
        return rows

    def get_batch_model_ineligibility(self, provider_id):
        return set(self.ineligible.get(int(provider_id), set()))

    def record_model_batch_ineligibility(self, provider_id, model_id, detail=""):
        self.eligibility_records.append((int(provider_id), int(model_id), detail))
        self.ineligible.setdefault(int(provider_id), set()).add(int(model_id))

    def get_provider_model_deployments(self, provider_id):
        return [row for row in self.deployments if int(row["provider_id"]) == int(provider_id)]

    def claim_batch_for_settlement(self, batch_object_id, lease_seconds=1800):
        return False  # the settlement tests drive the latch themselves

    def release_batch_settlement(self, batch_object_id):
        pass

    def mark_batch_settled(self, batch_object_id):
        pass

    def count_nonterminal_batches_for_input_file(self, input_file_id):
        states = {"validating", "in_progress", "cancelling"}
        return sum(
            1
            for row in self.local_batches.values()
            if row["input_file_id"] == input_file_id and row["status"] in states
        )

    def update_batch_object_status(self, upstream_id, status):
        self.status_updates.append((upstream_id, status))

    def delete_batch_object(self, batch_object_id):
        self.deleted.append(batch_object_id)
        for key, row in list(self.owned.items()):
            if row.get("id") == batch_object_id:
                del self.owned[key]

    # locally held objects
    def store_local_batch_file(self, *, upstream_id, content, filename, api_key_id, team_id, user_id, purpose="batch"):
        row = {
            "id": 1000 + len(self.stored_files),
            "kind": "file",
            "execution": "logos",
            "upstream_id": upstream_id,
            "filename": filename,
            "size_bytes": len(content),
            "status": purpose,
            "team_id": team_id,
            "api_key_id": api_key_id,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self.stored_files[upstream_id] = (row, content)
        self.owned[("file", upstream_id)] = row
        return row["id"]

    def get_local_object_by_upstream_id(self, kind, upstream_id):
        if kind == "file" and upstream_id in self.stored_files:
            return self.stored_files[upstream_id][0]
        return self.local_batches.get(upstream_id)

    def get_local_batch_file_content(self, batch_object_id):
        for row, content in self.stored_files.values():
            if row["id"] == batch_object_id:
                return content
        return None

    def create_local_batch(
        self,
        *,
        upstream_id,
        input_file_id,
        endpoint,
        completion_window,
        metadata,
        total_requests,
        api_key_id,
        team_id,
        user_id,
    ):
        row = {
            "id": 2000 + len(self.local_batches),
            "kind": "batch",
            "execution": "logos",
            "upstream_id": upstream_id,
            "input_file_id": input_file_id,
            "endpoint": endpoint,
            "completion_window": completion_window,
            "request_metadata": metadata,
            "total_requests": total_requests,
            "completed_requests": 0,
            "failed_requests": 0,
            "status": "validating",
            "team_id": team_id,
            "api_key_id": api_key_id,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self.local_batches[upstream_id] = row
        self.owned[("batch", upstream_id)] = row
        return row["id"]

    def get_local_batch(self, upstream_id):
        return self.local_batches.get(upstream_id)

    def request_local_batch_cancel(self, batch_object_id):
        self.cancelled.append(batch_object_id)
        for row in self.local_batches.values():
            if row["id"] == batch_object_id:
                row["status"] = "cancelling"

    # logging + budget
    def log_usage(self, **kwargs):
        self.log_usage_kwargs = kwargs
        return {"log-id": 42}, 200

    def update_log_entry_metrics(self, **kwargs):
        self.finalization = kwargs

    def get_api_key_budget_limit(self, api_key_id):
        return 100 if self.budget_error else None

    def get_api_key_budget_usage(self, api_key_id, month_start):
        return 500 if self.budget_error else 0

    def get_team(self, team_id):
        return None


def _patch_env(monkeypatch, db, upstream, auth=None):
    """Point the Batch API at a fake DB, a canned upstream and a fixed key."""
    seen = []

    def handler(request):
        seen.append(request)
        return upstream(request)

    monkeypatch.setattr(batch_api, "authenticate_api_key", lambda headers: auth or _auth())
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def test_batch_routes_are_registered_before_the_catch_alls():
    operations = (
        "files",
        "batches",
        "files/{file_id}",
        "files/{file_id}/content",
        "batches/{batch_id}",
        "batches/{batch_id}/cancel",
    )
    paths = [route.path for route in main.app.routes]
    for prefix in ("v1", "openai", "jobs/v1", "jobs/openai"):
        for operation in operations:
            assert f"/{prefix}/{operation}" in paths, f"missing route /{prefix}/{operation}"
        assert paths.index(f"/{prefix}/files") < paths.index(f"/{prefix}/{{path:path}}")
        assert paths.index(f"/{prefix}/batches") < paths.index(f"/{prefix}/{{path:path}}")


def test_file_upload_forwards_the_rewritten_file_and_records_ownership(monkeypatch):
    db = _FakeDB([AZURE_PROVIDER], AZURE_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc", "object": "file"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 200
    assert str(seen[0].url) == "https://res.openai.azure.com/openai/v1/files"
    # The model name the client used is translated to the Azure deployment.
    assert b'"model": "gpt-41"' in seen[0].content
    assert db.registered == [
        {
            "kind": "file",
            "upstream_id": "file-abc",
            "provider_id": 8,
            "api_key_id": 11,
            "team_id": OWN_TEAM,
            "user_id": 13,
            # The models the file names are kept on the row: a later refusal
            # by the provider is the evidence for which model to mark.
            "models": ["gpt-4.1"],
        }
    ]
    assert db.log_usage_kwargs["input_payload"]["requests"] == 1
    assert db.finalization["result_status"] == "success"


def test_an_unpermitted_model_never_reaches_the_upstream(monkeypatch):
    db = _FakeDB([AZURE_PROVIDER], AZURE_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line(model="gpt-5.6-luna")), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "model_not_permitted"
    assert seen == []


def test_only_purpose_batch_is_accepted(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("data.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "fine-tune"},
    )

    assert resp.status_code == 400
    assert seen == []


def test_batch_creation_requires_an_input_file_the_team_owns(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-someone-else"): _remote(5, OTHER_TEAM)},
    )
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_1"}))

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-someone-else", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 404
    assert seen == []


def test_batch_creation_registers_the_new_batch(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
    )
    body = {"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"}
    seen = _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(
            200, json={"id": "batch_1", "status": "validating", "input_file_id": "file-own"}
        ),
    )

    resp = client.post("/v1/batches", json=body)

    assert resp.status_code == 200
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content) == body
    assert db.registered[0]["kind"] == "batch"
    assert db.registered[0]["upstream_id"] == "batch_1"
    assert db.registered[0]["team_id"] == OWN_TEAM


def test_a_key_over_budget_cannot_start_a_batch(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
        budget_error=True,
    )
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_1"}))

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 402
    assert seen == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/batches/batch_other"),
        ("POST", "/v1/batches/batch_other/cancel"),
        ("GET", "/v1/files/file_other"),
        ("GET", "/v1/files/file_other/content"),
        ("DELETE", "/v1/files/file_other"),
    ],
)
def test_another_teams_object_is_indistinguishable_from_a_missing_one(monkeypatch, method, path):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={
            ("batch", "batch_other"): _remote(5, OTHER_TEAM),
            ("file", "file_other"): _remote(6, OTHER_TEAM),
        },
    )
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "leaked"}))

    resp = client.request(method, path)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    # Nothing was asked of the provider, so the shared credential never touched
    # another team's object.
    assert seen == []


def test_an_id_logos_never_minted_is_a_404(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_x"}))

    resp = client.get("/v1/batches/batch_x")

    assert resp.status_code == 404
    assert seen == []


def test_a_team_less_key_cannot_reach_another_users_objects(monkeypatch):
    # Both keys are team-less, so their objects carry team_id = NULL. A scope
    # on "team_id IS NULL" would make every personal key on the instance the
    # owner of every other one's batches; the user, then the key, is what
    # separates them.
    personal = {
        "id": 5,
        "team_id": None,
        "user_id": 13,
        "api_key_id": 21,
        "provider_id": 7,
        "execution": "provider",
        "settled_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS, owned={("batch", "batch_p"): personal})
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "leaked"}))
    stranger = SimpleNamespace(
        key_value="lg-other",
        api_key_id=22,
        api_key_name="other-key",
        key_type="user",
        team_id=None,
        user_id=14,
        environment="test",
        log_level="BILLING",
        settings={},
        default_priority=0,
    )
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "leaked"}), auth=stranger)

    # Another unteamed user is answered exactly like an unknown id, and the
    # listing shows none of that user's objects either.
    assert client.get("/v1/batches/batch_p").status_code == 404
    listed = client.get("/v1/batches")
    assert listed.status_code == 200
    assert listed.json()["data"] == []
    assert seen == []

    # The owning user (team-less like the object) reaches it.
    _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(200, json={"id": "batch_p", "status": "in_progress"}),
        auth=_auth(api_key_id=21, team_id=None),
    )
    resp = client.get("/v1/batches/batch_p")
    assert resp.status_code == 200
    assert resp.json()["id"] == "batch_p"


def test_a_listing_is_answered_from_logos_own_record(monkeypatch):
    # Not forwarded: the shared upstream credential sees every team's objects,
    # and Logos knows about the batches it ran itself, which no provider does.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={
            ("batch", "batch_mine"): _remote(1, OWN_TEAM, upstream_id="batch_mine", status="completed"),
            ("batch", "batch_theirs"): _remote(2, OTHER_TEAM, upstream_id="batch_theirs"),
        },
    )
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"data": [{"id": "leaked"}]}))

    resp = client.get("/v1/batches")

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["data"]] == ["batch_mine"]
    assert resp.json()["data"][0]["status"] == "completed"
    assert seen == []


def test_polling_records_the_status_and_settles_a_finished_batch(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("batch", "batch_1"): _remote(77, OWN_TEAM)},
    )
    finished = {"id": "batch_1", "status": "completed", "output_file_id": "file-out"}
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json=finished))

    settled = []
    monkeypatch.setattr(batch_api, "_schedule_settlement", lambda p, o, b: settled.append((o["id"], b["status"])))

    resp = client.get("/v1/batches/batch_1")

    assert resp.status_code == 200
    assert db.status_updates == [("batch_1", "completed")]
    assert settled == [(77, "completed")]


def test_a_poll_registers_the_result_file_the_provider_minted(monkeypatch):
    # The provider mints the output (and error) file under the shared
    # credential: it shows up in the provider's file list for every key that
    # may use the provider. Without an ownership row of its own, the batch
    # owner's result download would be a 404 while a stranger's would work.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("batch", "batch_1"): _remote(77, OWN_TEAM)},
    )
    _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(
            200,
            json={
                "id": "batch_1",
                "status": "completed",
                "output_file_id": "file-out",
                "error_file_id": "file-err",
            },
        ),
    )
    monkeypatch.setattr(batch_api, "_schedule_settlement", lambda *args: None)

    assert client.get("/v1/batches/batch_1").status_code == 200

    file_rows = [row for (kind, _), row in db.owned.items() if kind == "file"]
    assert {row["upstream_id"] for row in file_rows} == {"file-out", "file-err"}
    assert all(row["team_id"] == OWN_TEAM for row in file_rows)

    # And the owner can now download the result through the files route.
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, content=b'{"custom_id": "one"}\n'))
    download = client.get("/v1/files/file-out/content")
    assert download.status_code == 200
    assert download.content == b'{"custom_id": "one"}\n'


def test_an_unfinished_batch_is_not_settled(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("batch", "batch_1"): _remote(77, OWN_TEAM)},
    )
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_1", "status": "in_progress"}))
    settled = []
    monkeypatch.setattr(batch_api, "_schedule_settlement", lambda p, o, b: settled.append(o))

    assert client.get("/v1/batches/batch_1").status_code == 200
    assert settled == []


def test_file_content_comes_back_as_raw_bytes(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-out"): _remote(3, OWN_TEAM)},
    )
    payload = b'{"custom_id": "one", "response": {"status_code": 200}}\n'
    _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(200, content=payload, headers={"content-type": "application/jsonl"}),
    )

    resp = client.get("/v1/files/file-out/content")

    assert resp.status_code == 200
    assert resp.content == payload


def test_a_deleted_provider_file_leaves_no_ownership_row_behind(monkeypatch):
    # The provider's delete is forwarded, and a success means the object is
    # gone there: keeping the row would park a dead id in the listing, and a
    # later creation naming it would pass the local ownership check only to
    # fail upstream.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
    )
    seen = _patch_env(
        monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-own", "object": "file", "deleted": True})
    )

    resp = client.delete("/v1/files/file-own")

    assert resp.status_code == 200
    assert [request.method for request in seen] == ["DELETE"]
    assert db.deleted == [5]

    # The listing, answered from Logos's own record, no longer shows it.
    listed = client.get("/v1/files")
    assert listed.json()["data"] == []


def test_a_failed_provider_delete_keeps_the_ownership_row(monkeypatch):
    # The other side of the same coin: the file is only gone from Logos's
    # books when the provider says it is gone.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
    )
    _patch_env(monkeypatch, db, lambda request: httpx.Response(500))

    resp = client.delete("/v1/files/file-own")

    assert resp.status_code == 500
    assert db.deleted == []
    assert client.get("/v1/files").json()["data"] != []


def test_an_upstream_error_is_passed_through_and_logged(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
    )
    _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(400, json={"error": {"message": "input file is empty", "type": "invalid"}}),
    )

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "input file is empty"
    assert db.finalization["result_status"] == "error"
    assert "input file is empty" in db.finalization["error_message"]


def test_an_unrecordable_upload_is_removed_upstream_and_reported(monkeypatch):
    # The provider has the file but nobody at Logos knows who owns it: with
    # the shared credential that object is reachable by every key. Rather
    # than return success for an unowned object, Logos removes it again and
    # says so.
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    db.fail_registration = True
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "batch_ownership_unrecorded"
    # The provider object is gone again: minted, then deleted.
    assert [request.method for request in seen] == ["POST", "DELETE"]
    assert str(seen[-1].url).endswith("/v1/files/file-abc")
    # Every failed attempt on the shared session was rolled back before the
    # next one ran, so the retries actually retried the write instead of
    # raising PendingRollbackError.
    assert db.session.rollback.call_count == 3


def test_an_unrecordable_batch_creation_is_cancelled_upstream_and_reported(monkeypatch):
    # The batch equivalent of the upload case above — with one difference that
    # matters: the Batch API has no delete. A job that is minted and left
    # unowned would keep running on the shared credential, so the only
    # cleanup is the cancel the API does have.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM)},
    )
    db.fail_registration = "batch"  # the file row stays, the batch row does not
    seen = _patch_env(
        monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_1", "status": "validating"})
    )

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "batch_ownership_unrecorded"
    # Minted, then stopped — with a cancel, because a DELETE would 405.
    assert [request.method for request in seen] == ["POST", "POST"]
    assert str(seen[-1].url).endswith("/v1/batches/batch_1/cancel")


def test_an_unreachable_upstream_is_a_502(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    _patch_env(monkeypatch, db, boom)

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "batch_upstream_unreachable"


def test_an_unauthenticated_request_never_reaches_the_upstream(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    def reject(headers):
        raise HTTPException(status_code=401, detail="Invalid or inactive logos key")

    monkeypatch.setattr(batch_api, "authenticate_api_key", reject)

    resp = client.post("/v1/batches", json={"input_file_id": "file-own"})

    assert resp.status_code == 401
    assert seen == []
    assert db.log_usage_kwargs is None


def test_the_mirrors_reach_the_same_forward(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("batch", "batch_1"): _remote(7, OWN_TEAM)},
    )
    seen = _patch_env(
        monkeypatch, db, lambda request: httpx.Response(200, json={"id": "batch_1", "status": "in_progress"})
    )

    for prefix in ("/v1", "/openai", "/jobs/v1", "/jobs/openai"):
        assert client.get(f"{prefix}/batches/batch_1").status_code == 200
    assert {str(request.url) for request in seen} == {"https://api.openai.com/v1/batches/batch_1"}


def test_credentials_are_not_sent_over_an_insecure_transport(monkeypatch):
    db = _FakeDB([{**OPENAI_PROVIDER, "base_url": "http://plain.example.com/v1"}], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 502
    assert seen == []


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


OUTPUT_FILE = (
    json.dumps(
        {
            "custom_id": "one",
            "response": {
                "status_code": 200,
                "body": {"model": "gpt-4.1-2025-04-14", "usage": {"prompt_tokens": 120, "completion_tokens": 30}},
            },
        }
    )
    + "\n"
    + json.dumps(
        {
            "custom_id": "two",
            "error": {"message": "context length exceeded"},
            "response": {"status_code": 400, "body": {"model": "gpt-4.1"}},
        }
    )
    + "\n"
).encode()

INPUT_FILE = _jsonl(_line("one"), _line("two"))


class _SettlingDB:
    def __init__(self, claimable=True, fail_record_once=False):
        self.claimable = claimable
        self.fail_record_once = fail_record_once
        self.claims = 0
        self.released = 0
        self.settled = 0
        self.rows = []
        self.booked = set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def claim_batch_for_settlement(self, batch_object_id, lease_seconds=1800):
        self.claims += 1
        return self.claimable

    def release_batch_settlement(self, batch_object_id):
        self.released += 1

    def mark_batch_settled(self, batch_object_id):
        self.settled += 1

    def get_api_key_logging_context(self, api_key_id):
        return {"environment": "test", "log_level": "BILLING"}

    def get_provider_model_deployments(self, provider_id):
        return [
            {
                "model_id": 25,
                "model_name": "gpt-4.1",
                "endpoint": "https://api.openai.com/v1/chat/completions",
            }
        ]

    def record_batch_usage(self, rows, chunk_size=500):
        # Models the ledger's ON CONFLICT (request_id) DO NOTHING: a row an
        # earlier attempt of the same settlement already booked is skipped,
        # and only the newly written rows are counted.
        written = 0
        for row in rows:
            if row["request_id"] in self.booked:
                continue
            self.booked.add(row["request_id"])
            self.rows.append(row)
            written += 1
        if self.fail_record_once:
            # The chunks committed and then the process died: the rows are in
            # the ledger, but the batch was never stamped settled.
            self.fail_record_once = False
            raise RuntimeError("the ledger connection dropped")
        return written


def _files_upstream(request):
    if request.url.path.endswith("/file-out/content"):
        return httpx.Response(200, content=OUTPUT_FILE)
    if request.url.path.endswith("/file-in/content"):
        return httpx.Response(200, content=INPUT_FILE)
    return httpx.Response(404, json={"error": "no such file"})


@pytest.mark.asyncio
async def test_settlement_books_one_usage_row_per_result(monkeypatch):
    db = _SettlingDB()
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(
        batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_files_upstream))
    )

    owner = {"id": 77, "api_key_id": 11, "team_id": OWN_TEAM, "user_id": 13, "upstream_id": "batch_1"}
    written = await settle_batch(
        OPENAI_PROVIDER,
        owner,
        {"status": "completed", "output_file_id": "file-out", "input_file_id": "file-in"},
    )

    assert written == 2
    assert db.settled == 1  # stamped only after the rows were written
    ok, failed = db.rows
    assert ok["usage"]["prompt_tokens"] == 120
    assert ok["usage"]["completion_tokens"] == 30
    assert ok["model_id"] == 25  # the dated model name maps back to the model
    assert ok["service_tier"] == "batch"  # what makes the batch rate apply
    assert ok["team_id"] == OWN_TEAM
    assert ok["result_status"] == "success"
    assert failed["result_status"] == "error"
    assert "context length" in failed["error_message"]
    # Scoped to this batch, from the line's own custom_id: that stable id is
    # what makes a retried settlement skip the rows it already booked.
    assert (ok["request_id"], failed["request_id"]) == ("batch-77-one", "batch-77-two")


@pytest.mark.asyncio
async def test_a_batch_is_settled_only_once(monkeypatch):
    db = _SettlingDB(claimable=False)
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(
        batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_files_upstream))
    )

    written = await settle_batch(
        OPENAI_PROVIDER, {"id": 77, "api_key_id": 11, "team_id": OWN_TEAM}, {"output_file_id": "file-out"}
    )

    assert written == 0
    assert db.rows == []
    assert db.settled == 0


@pytest.mark.asyncio
async def test_an_unreadable_result_file_releases_the_lease(monkeypatch):
    # Otherwise a transient failure would drop a whole batch's cost silently.
    # The lease, not a settled stamp, is what is released: the batch must stay
    # claimable for the retry.
    db = _SettlingDB()
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(
        batch_api,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    written = await settle_batch(
        OPENAI_PROVIDER, {"id": 77, "api_key_id": 11, "team_id": OWN_TEAM}, {"output_file_id": "file-out"}
    )

    assert written == 0
    assert db.released == 1
    assert db.settled == 0


@pytest.mark.asyncio
async def test_a_settlement_retry_books_the_rows_only_once(monkeypatch):
    # The usage chunks commit before the batch is stamped settled, so a
    # settlement that dies in between is retried with the rows already in the
    # ledger: the retry skips them on their stable request id, bills nothing
    # twice, and is what finally stamps the batch.
    db = _SettlingDB(fail_record_once=True)
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)
    monkeypatch.setattr(
        batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_files_upstream))
    )
    owner = {"id": 77, "api_key_id": 11, "team_id": OWN_TEAM, "user_id": 13, "upstream_id": "batch_1"}
    batch_body = {"status": "completed", "output_file_id": "file-out", "input_file_id": "file-in"}

    assert await settle_batch(OPENAI_PROVIDER, owner, batch_body) == 0
    assert db.released == 1 and db.settled == 0
    assert len(db.rows) == 2  # the partial commit made it into the ledger

    assert await settle_batch(OPENAI_PROVIDER, owner, batch_body) == 0  # nothing new to book
    assert len(db.rows) == 2  # ... and nothing was booked twice
    assert db.settled == 1


@pytest.mark.asyncio
async def test_the_reconciler_settles_a_batch_nobody_polled(monkeypatch):
    settling = _SettlingDB()

    class _ReconcileDB(_SettlingDB):
        def get_unsettled_batches(self, limit=50):
            return [
                {
                    "id": 77,
                    "upstream_id": "batch_1",
                    "provider_id": 7,
                    "api_key_id": 11,
                    "team_id": OWN_TEAM,
                    "user_id": 13,
                    "status": "in_progress",
                }
            ]

        def get_batch_provider(self, provider_id):
            return OPENAI_PROVIDER

        def update_batch_object_status(self, upstream_id, status):
            settling.rows.append(("status", upstream_id, status))

        def claim_batch_for_settlement(self, batch_object_id, lease_seconds=1800):
            return settling.claim_batch_for_settlement(batch_object_id, lease_seconds)

        def release_batch_settlement(self, batch_object_id):
            settling.release_batch_settlement(batch_object_id)

        def mark_batch_settled(self, batch_object_id):
            settling.mark_batch_settled(batch_object_id)

        def get_api_key_logging_context(self, api_key_id):
            return settling.get_api_key_logging_context(api_key_id)

        def get_provider_model_deployments(self, provider_id):
            return settling.get_provider_model_deployments(provider_id)

        def record_batch_usage(self, rows, chunk_size=500):
            return settling.record_batch_usage(rows)

    monkeypatch.setattr(batch_api, "DBManager", _ReconcileDB)

    def upstream(request):
        if request.url.path.endswith("/batches/batch_1"):
            return httpx.Response(200, json={"id": "batch_1", "status": "completed", "output_file_id": "file-out"})
        return _files_upstream(request)

    monkeypatch.setattr(batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)))

    assert await reconcile_batches_once() == 2
    assert ("status", "batch_1", "completed") in settling.rows
    assert settling.settled == 1


@pytest.mark.asyncio
async def test_a_failed_batch_nobody_polled_teaches_the_next_file_to_run_in_logos(monkeypatch):
    # A batch the client never polls is the reconciler's to find, and its
    # failure must teach the routing there as well as on the client's own
    # poll: the unsettled-batches query does not carry the input file id, so
    # the learning takes it from the provider's answer.
    class _ReconcileDB(_FakeDB):
        def get_unsettled_batches(self, limit=50):
            # Shaped as the query selects it: no input_file_id.
            return [
                {
                    "id": 77,
                    "upstream_id": "batch_1",
                    "provider_id": 7,
                    "api_key_id": 11,
                    "team_id": OWN_TEAM,
                    "user_id": 13,
                    "status": "in_progress",
                }
            ]

    db = _ReconcileDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-in"): _remote(5, OWN_TEAM, models=["gpt-4.1"])},
    )
    monkeypatch.setattr(batch_api, "DBManager", lambda: db)

    def upstream(request):
        if request.url.path.endswith("/batches/batch_1"):
            return httpx.Response(
                200,
                json={
                    "id": "batch_1",
                    "status": "failed",
                    "input_file_id": "file-in",
                    "error": {"message": "The model 'gpt-4.1' is not supported on the batch SKU."},
                },
            )
        return httpx.Response(404, json={"error": "no such object"})

    monkeypatch.setattr(batch_api, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)))

    await reconcile_batches_once()

    # The failure named the model, so only that model is recorded — and the
    # record is what the next upload reads.
    assert [record[:2] for record in db.eligibility_records] == [(7, 25)]

    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))
    upload = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )
    assert upload.status_code == 200
    assert upload.json()["logos_execution"] == "logos"
    # The learned routing kept the file out of the provider entirely.
    assert seen == []


def test_a_dated_model_name_falls_back_to_the_configured_model():
    index = {"gpt-4.1": 25, "gpt-41": 25, "gpt-4.1-mini": 24}
    assert batch_api._model_id_for(index, "gpt-4.1-2025-04-14") == 25
    assert batch_api._model_id_for(index, "gpt-4.1-mini-2025-04-14") == 24
    assert batch_api._model_id_for(index, "gpt-41") == 25
    assert batch_api._model_id_for(index, "something-else") is None
    assert batch_api._model_id_for(index, None) is None


def test_a_result_row_without_a_model_falls_back_to_the_input_file():
    rows = batch_api._usage_rows_from_output(
        json.dumps({"custom_id": "one", "error": {"message": "boom"}}).encode() + b"\n",
        {"api_key_id": 11, "team_id": OWN_TEAM, "user_id": 13},
        OPENAI_PROVIDER,
        {"gpt-4.1": 25},
        {"one": "gpt-4.1"},
        {"environment": "test", "log_level": "BILLING"},
    )
    assert rows[0]["model_id"] == 25
    assert rows[0]["result_status"] == "error"


def test_the_batch_operation_dataclass_knows_its_shapes():
    upload = BatchOperation(resource="files", method="POST", path="v1/files")
    assert upload.is_file_upload and not upload.is_batch_creation and not upload.is_listing
    creation = BatchOperation(resource="batches", method="POST", path="v1/batches")
    assert creation.is_batch_creation and not creation.is_file_upload
    listing = BatchOperation(resource="batches", method="GET", path="v1/batches")
    assert listing.is_listing


# ---------------------------------------------------------------------------
# Batches Logos runs itself
# ---------------------------------------------------------------------------


def _local_line(custom_id="one", model="qwen3-32b"):
    return _line(custom_id, model=model)


def test_a_model_only_a_worker_node_serves_is_run_by_logos(monkeypatch):
    # A worker node has no Batch API at all, so there is nothing to forward to;
    # the batch becomes low-priority requests here instead of a 501.
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_local_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "file"
    assert body["id"].startswith("file-")
    assert body["logos_execution"] == "logos"
    assert seen == []  # nothing was uploaded to a provider
    assert db.log_usage_kwargs["input_payload"]["execution"] == "logos"


def test_a_cloud_model_its_provider_cannot_batch_is_run_by_logos(monkeypatch):
    # Exactly the gpt-5.6 case: the model is served on the provider, but not on
    # its Batch API, so the file names a model the provider's batch endpoint
    # would reject. Running it here keeps the same client working.
    unbatchable = [
        {
            "model_id": 92,
            "model_name": "gpt-5.6-luna",
            "endpoint": "https://res.openai.azure.com/openai/deployments/gpt-5.6-luna/responses",
            "provider_id": 99,  # a provider the key may use but which is not batch-capable
            "provider_type": "cloud",
            "cloud_provider_type": "azure",
        }
    ]
    db = _FakeDB([AZURE_PROVIDER], AZURE_DEPLOYMENTS + unbatchable)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line(model="gpt-5.6-luna")), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 200
    assert resp.json()["logos_execution"] == "logos"
    assert seen == []


def test_a_model_the_provider_refused_before_runs_in_logos(monkeypatch):
    # The model is hosted on the batch-capable provider — through a Standard
    # deployment — but a refusal recorded before marked it as not batchable
    # there. Hosting alone must not qualify it: forwarding would just fail
    # the batch the same way it failed before.
    hosted_but_not_batchable = [
        {
            "model_id": 92,
            "model_name": "gpt-5.6-luna",
            "endpoint": "https://res.openai.azure.com/openai/deployments/gpt-5.6-luna/responses",
            "provider_id": 8,  # the batch-capable provider itself
            "provider_type": "cloud",
            "cloud_provider_type": "azure",
        }
    ]
    db = _FakeDB([AZURE_PROVIDER], AZURE_DEPLOYMENTS + hosted_but_not_batchable)
    db.ineligible[8] = {92}
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line(model="gpt-5.6-luna")), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 200
    assert resp.json()["logos_execution"] == "logos"
    assert seen == []


def test_a_refused_creation_teaches_the_next_file_to_run_in_logos(monkeypatch):
    # The provider does not publish which of its models it offers for batch,
    # so its refusal is the only source: a creation refused for the model
    # records it, and the same file uploaded again is routed to Logos instead
    # of failing the same way.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM, models=["gpt-4.1"])},
    )
    seen = _patch_env(
        monkeypatch,
        db,
        lambda request: httpx.Response(
            400, json={"error": {"message": "The model 'gpt-4.1' is not supported on the batch SKU."}}
        ),
    )

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 400
    # The refusal named the model, so only that model is recorded — and the
    # record is what the next upload reads.
    assert [record[:2] for record in db.eligibility_records] == [(7, 25)]

    upload = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )
    assert upload.status_code == 200
    assert upload.json()["logos_execution"] == "logos"
    # The learned routing kept the file out of the provider entirely. The GET
    # is the in-request rerun's attempt to pull the input back from the
    # provider, which this canned upstream also refuses — so the refusal stays
    # the answer here, and the rerun is covered by its own test.
    assert [request.method for request in seen] == ["POST", "GET"]


def test_a_refused_auto_creation_is_rerun_locally_on_the_first_request(monkeypatch):
    # Auto mode means "forward when that can work". A creation the provider
    # refused with a model-availability error has just said it cannot, so the
    # same input is pulled back from the provider and run here: the first
    # request still ends in a batch, and no second upload is needed.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM, models=["gpt-4.1"])},
    )
    started = []
    monkeypatch.setattr(batch_api, "_start_local_batch", lambda row: started.append(row["upstream_id"]))

    def upstream(request):
        if request.url.path.endswith("/files/file-own/content"):
            return httpx.Response(200, content=_jsonl(_line("one"), _line("two")))
        return httpx.Response(
            400, json={"error": {"message": "The model 'gpt-4.1' is not supported on the batch SKU."}}
        )

    seen = _patch_env(monkeypatch, db, upstream)

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "batch"
    assert body["logos_execution"] == "logos"
    assert body["request_counts"]["total"] == 2
    # The input was stored here under a fresh id, named after the provider's file.
    assert body["input_file_id"].startswith("file-")
    assert db.stored_files[body["input_file_id"]][0]["filename"] == "file-own_rerun.jsonl"
    assert started == [body["id"]]
    # The refusal taught the routing alongside the rerun: the model is marked,
    # so the next upload of it stays local without another refusal.
    assert [record[:2] for record in db.eligibility_records] == [(7, 25)]
    # The creation went out once, and the input came back once.
    assert [request.method for request in seen] == ["POST", "GET"]


def test_a_named_provider_keeps_the_refused_creation_refused(monkeypatch):
    # The rerun is what "auto" promises. A provider the client named was
    # demanded, not suggested: its refusal is the answer, unrerun.
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("file", "file-own"): _remote(5, OWN_TEAM, models=["gpt-4.1"])},
    )

    def upstream(request):
        if request.url.path.endswith("/files/file-own/content"):
            return httpx.Response(200, content=_jsonl(_line("one")))
        return httpx.Response(
            400, json={"error": {"message": "The model 'gpt-4.1' is not supported on the batch SKU."}}
        )

    seen = _patch_env(monkeypatch, db, upstream)

    resp = client.post(
        "/v1/batches",
        json={"input_file_id": "file-own", "endpoint": "/v1/chat/completions", "completion_window": "24h"},
        headers={batch_api.BATCH_PROVIDER_HEADER: "openai"},
    )

    assert resp.status_code == 400
    assert db.local_batches == {}
    assert db.stored_files == {}
    assert [request.method for request in seen] == ["POST"]


def test_the_execution_header_forces_a_local_run(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
        headers={batch_api.BATCH_EXECUTION_HEADER: "logos"},
    )

    assert resp.status_code == 200
    assert resp.json()["logos_execution"] == "logos"
    assert seen == []


def test_forwarding_is_preferred_when_the_provider_can_run_it(monkeypatch):
    # The provider's batch endpoint is where the discount is, so 'auto' only
    # falls back to a local run when forwarding cannot work.
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "file-abc"
    assert len(seen) == 1


def test_demanding_a_provider_that_cannot_run_the_model_is_an_error(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "file-abc"}))

    resp = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_local_line()), "application/jsonl")},
        data={"purpose": "batch"},
        headers={batch_api.BATCH_EXECUTION_HEADER: "provider"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "model_not_available_for_batch"
    assert seen == []


def test_a_local_batch_is_created_and_reported_in_the_openai_shape(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "unused"}))
    started = []
    monkeypatch.setattr(batch_api, "_start_local_batch", lambda row: started.append(row["upstream_id"]))

    upload = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_local_line("a"), _local_line("b")), "application/jsonl")},
        data={"purpose": "batch"},
    )
    file_id = upload.json()["id"]

    created = client.post(
        "/v1/batches",
        json={"input_file_id": file_id, "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    assert created.status_code == 200
    body = created.json()
    assert body["object"] == "batch"
    assert body["status"] == "validating"
    assert body["input_file_id"] == file_id
    assert body["request_counts"] == {"total": 2, "completed": 0, "failed": 0}
    # Started immediately rather than waiting for the next poll of the runner.
    assert started == [body["id"]]


def test_a_local_batch_is_polled_and_cancelled_through_the_same_routes(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "unused"}))
    monkeypatch.setattr(batch_api, "_start_local_batch", lambda row: None)

    upload = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_local_line()), "application/jsonl")},
        data={"purpose": "batch"},
    )
    batch_id = client.post("/v1/batches", json={"input_file_id": upload.json()["id"]}).json()["id"]

    polled = client.get(f"/v1/batches/{batch_id}")
    assert polled.status_code == 200
    assert polled.json()["id"] == batch_id

    cancelled = client.post(f"/v1/batches/{batch_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelling"
    assert db.cancelled  # the runner stops before its next line
    assert seen == []  # no provider was ever involved


def test_a_local_result_file_is_downloaded_through_the_files_route(monkeypatch):
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    seen = _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "unused"}))
    content = _jsonl(_local_line())

    upload = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", content, "application/jsonl")},
        data={"purpose": "batch"},
    )
    file_id = upload.json()["id"]

    downloaded = client.get(f"/v1/files/{file_id}/content")

    assert downloaded.status_code == 200
    # The stored file is the validated one, so it round-trips as JSONL.
    assert json.loads(downloaded.content.splitlines()[0])["custom_id"] == "one"
    assert seen == []


def test_an_input_file_is_not_deletable_while_a_batch_still_runs_on_it(monkeypatch):
    # The runner reads the input's bytes when it starts the batch, not when
    # the batch is created. A delete in between would strand the batch:
    # accepted to run, then finding no content. So the delete waits for
    # terminal.
    db = _FakeDB([OPENAI_PROVIDER], OPENAI_DEPLOYMENTS + LOCAL_DEPLOYMENTS)
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "unused"}))
    monkeypatch.setattr(batch_api, "_start_local_batch", lambda row: None)  # keep it nonterminal

    file_id = client.post(
        "/v1/files",
        files={"file": ("batch.jsonl", _jsonl(_local_line()), "application/jsonl")},
        data={"purpose": "batch"},
    ).json()["id"]
    client.post(
        "/v1/batches",
        json={"input_file_id": file_id, "endpoint": "/v1/chat/completions", "completion_window": "24h"},
    )

    refused = client.delete(f"/v1/files/{file_id}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "batch_input_file_in_use"

    # Every referencing batch terminal -> the same delete goes through.
    batch_row = next(row for row in db.local_batches.values() if row["input_file_id"] == file_id)
    batch_row["status"] = "completed"
    allowed = client.delete(f"/v1/files/{file_id}")
    assert allowed.status_code == 200
    assert allowed.json()["deleted"] is True


def test_another_teams_local_object_is_a_404(monkeypatch):
    db = _FakeDB(
        [OPENAI_PROVIDER],
        OPENAI_DEPLOYMENTS,
        owned={("batch", "batch_local"): {"id": 9, "team_id": OTHER_TEAM, "execution": "logos"}},
    )
    _patch_env(monkeypatch, db, lambda request: httpx.Response(200, json={"id": "unused"}))

    assert client.get("/v1/batches/batch_local").status_code == 404


def test_a_local_batch_runs_its_lines_as_low_priority_requests(monkeypatch):
    # Each line goes through the ordinary pipeline, so it is authorised, routed,
    # logged and metered like any other request — which is why a Logos-run batch
    # needs no settlement pass.
    executed = []

    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        executed.append((path, body["model"], auth.default_priority, log_id))
        return {"status_code": 200, "data": {"model": body["model"], "usage": {"prompt_tokens": 5}}}

    stored = {}

    class _RunnerDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, batch_object_id, runner_id, lease_seconds):
            stored.setdefault("claims", []).append((batch_object_id, runner_id, lease_seconds))
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return {"id": 1000}

        def get_local_batch_file_content(self, object_id):
            return _jsonl(_local_line("a"), _local_line("b"))

        def get_api_key_by_id(self, api_key_id):
            return {
                "id": 11,
                "key_value": "lg-test",
                "name": "k",
                "key_type": "user",
                "team_id": OWN_TEAM,
                "user_id": 13,
                "environment": "test",
                "log": "BILLING",
                "settings": {},
                "default_priority": 10,
            }

        def get_local_batch_lines(self, object_id):
            return {}

        def update_local_batch_progress(self, object_id, runner_id, completed, failed, lease_seconds):
            return False

        def save_local_batch_lines(self, object_id, runner_id, rows):
            stored.setdefault("checkpoints", []).extend(rows)
            stored.setdefault("checkpoint_runners", []).append(runner_id)

        def log_usage(self, **kwargs):
            stored.setdefault("logged", []).append(kwargs)
            return {"log-id": 500 + len(stored["logged"])}, 200

        def store_local_batch_file(self, **kwargs):
            stored.update(kwargs)
            return 1

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            stored["finish"] = kwargs
            return True

    monkeypatch.setattr(batch_local, "DBManager", _RunnerDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    written = asyncio.run(
        batch_local.run_local_batch(
            {
                "id": 2000,
                "upstream_id": "batch_x",
                "input_file_id": "file-in",
                "api_key_id": 11,
                "team_id": OWN_TEAM,
                "user_id": 13,
                "status": "validating",
            }
        )
    )

    assert written and written.startswith("file-")
    assert [name for _, name, _, _ in executed] == ["qwen3-32b", "qwen3-32b"]
    # The key's own priority is 10 (HIGH); batch work runs at LOW regardless.
    assert {priority for _, _, priority, _ in executed} == {batch_local.LOCAL_BATCH_PRIORITY}
    # Each line opens its own usage-log row: that is what the pipeline writes
    # the response's tokens onto, so without it the work would cost money and
    # never reach the ledger.
    assert len(stored["logged"]) == 2
    assert {log_id for _, _, _, log_id in executed} == {501, 502}
    assert stored["logged"][0]["api_key_id"] == 11
    assert stored["finish"]["status"] == "completed"
    assert stored["finish"]["completed"] == 2
    assert stored["finish"]["failed"] == 0
    # The result file is the OpenAI batch output shape.
    row = json.loads(stored["content"].splitlines()[0])
    assert row["custom_id"] == "a"
    assert row["response"]["status_code"] == 200
    assert row["error"] is None
    # Every finished line is checkpointed durably: on a restart that is what
    # tells the runner which lines must not run (and bill) a second time.
    assert {checkpoint["custom_id"] for checkpoint in stored["checkpoints"]} == {"a", "b"}
    # The checkpoint write is bound to this holder: a runner deposed mid-batch
    # must not overwrite the rows the new holder wrote for the same lines.
    assert set(stored["checkpoint_runners"]) == {batch_local.RUNNER_ID}
    # The claim is the cross-process guard, and it carries this process' id
    # and the lease the other processes will wait on.
    assert stored["claims"] == [(2000, batch_local.RUNNER_ID, batch_local.LOCAL_BATCH_LEASE_TTL_S)]


def _runner_key_row(default_priority=1):
    return {
        "id": 11,
        "key_value": "lg-test",
        "name": "k",
        "key_type": "user",
        "team_id": OWN_TEAM,
        "user_id": 13,
        "environment": "test",
        "log": "BILLING",
        "settings": {},
        "default_priority": default_priority,
    }


def test_a_resumed_batch_skips_the_lines_already_checkpointed(monkeypatch):
    # A restart must not re-run (and re-bill) the lines the previous pass
    # finished: they are read back from the checkpoint, and only the missing
    # lines go through the pipeline.
    executed = []

    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        executed.append(body["model"])
        return {"status_code": 200, "data": {"usage": {"prompt_tokens": 5}}}

    stored = {}
    done = batch_local._result_row(_local_line("a"), {"status_code": 200, "data": {"usage": {"prompt_tokens": 5}}})[0]

    class _ResumeDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, batch_object_id, runner_id, lease_seconds):
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return {"id": 1000}

        def get_local_batch_file_content(self, object_id):
            return _jsonl(_local_line("a"), _local_line("b"))

        def get_api_key_by_id(self, api_key_id):
            return _runner_key_row()

        def get_local_batch_lines(self, object_id):
            return {"a": done}

        def update_local_batch_progress(self, object_id, runner_id, completed, failed, lease_seconds):
            return False

        def save_local_batch_lines(self, object_id, runner_id, rows):
            stored.setdefault("checkpoints", []).extend(rows)
            stored.setdefault("checkpoint_runners", []).append(runner_id)

        def log_usage(self, **kwargs):
            stored.setdefault("logged", []).append(kwargs)
            return {"log-id": 500 + len(stored["logged"])}, 200

        def store_local_batch_file(self, **kwargs):
            stored.update(kwargs)
            return 1

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            stored["finish"] = kwargs
            return True

    monkeypatch.setattr(batch_local, "DBManager", _ResumeDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    asyncio.run(
        batch_local.run_local_batch(
            {
                "id": 2003,
                "upstream_id": "batch_r",
                "input_file_id": "file-in",
                "api_key_id": 11,
                "team_id": OWN_TEAM,
                "user_id": 13,
                "status": "in_progress",  # left behind by a dead runner
            }
        )
    )

    assert len(executed) == 1  # only the line without a checkpoint ran
    assert len(stored["logged"]) == 1  # ... and was the only one billed
    assert stored["finish"]["completed"] == 2
    assert stored["finish"]["failed"] == 0
    # The output file carries both rows, in input order — the resumed one
    # from the checkpoint, the fresh one from this run.
    output = [json.loads(line) for line in stored["content"].splitlines()]
    assert [row["custom_id"] for row in output] == ["a", "b"]
    assert output[0] == done


def test_a_lost_lease_stops_the_runner_without_writing_results(monkeypatch):
    # A progress write that says "you no longer hold this batch" must stop the
    # runner before the next line: the new holder resumes from the checkpoints
    # already written, and two finishers would write two result files.
    executed = []

    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        executed.append(1)
        return {"status_code": 200, "data": {}}

    stored = {}

    class _LostLeaseDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, batch_object_id, runner_id, lease_seconds):
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return {"id": 1000}

        def get_local_batch_file_content(self, object_id):
            return _jsonl(_local_line("a"), _local_line("b"))

        def get_api_key_by_id(self, api_key_id):
            return _runner_key_row()

        def get_local_batch_lines(self, object_id):
            return {}

        def update_local_batch_progress(self, object_id, runner_id, completed, failed, lease_seconds):
            return None  # another runner took the batch over

        def save_local_batch_lines(self, object_id, runner_id, rows):
            stored.setdefault("checkpoints", []).extend(rows)

        def log_usage(self, **kwargs):
            return {"log-id": 600}, 200

        def store_local_batch_file(self, **kwargs):
            stored.update(kwargs)
            return 1

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            stored["finish"] = kwargs
            return True

    monkeypatch.setattr(batch_local, "DBManager", _LostLeaseDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    result = asyncio.run(
        batch_local.run_local_batch(
            {
                "id": 2004,
                "upstream_id": "batch_l",
                "input_file_id": "file-in",
                "api_key_id": 11,
                "team_id": OWN_TEAM,
                "user_id": 13,
                "status": "in_progress",
            }
        )
    )

    assert result is None  # no output file id: this runner wrote nothing
    assert executed == []
    assert "finish" not in stored
    assert "content" not in stored


def test_a_lease_lost_mid_chunk_cancels_the_lines_and_writes_nothing(monkeypatch):
    # A single line can run longer than the whole lease, so the heartbeat
    # refreshes it in chunks. When the heartbeat finds the lease gone, the
    # in-flight lines are cancelled — the new holder will run them, and a
    # cancelled line must not bill for the half it already spent — and this
    # runner checkpoints nothing and finalizes nothing.
    monkeypatch.setattr(batch_local, "LOCAL_BATCH_LEASE_TTL_S", 0.6)  # heartbeat every 0.2 s
    executed = []

    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        await asyncio.sleep(0.5)  # longer than the heartbeat interval
        executed.append(1)
        return {"status_code": 200, "data": {}}

    stored = {}

    class _MidChunkDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, object_id, runner_id, lease_seconds):
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return {"id": 1000}

        def get_local_batch_file_content(self, object_id):
            return _jsonl(_local_line("a"), _local_line("b"))

        def get_api_key_by_id(self, api_key_id):
            return _runner_key_row()

        def get_local_batch_lines(self, object_id):
            return {}

        def update_local_batch_progress(self, object_id, runner_id, completed, failed, lease_seconds):
            # The write before the chunk still holds the lease; the heartbeat
            # mid-chunk finds it gone. Counted in the closure: every
            # ``with DBManager()`` opens a fresh instance.
            stored["progress_calls"] = stored.get("progress_calls", 0) + 1
            return False if stored["progress_calls"] == 1 else None

        def save_local_batch_lines(self, object_id, runner_id, rows):
            stored.setdefault("checkpoints", []).extend(rows)

        def log_usage(self, **kwargs):
            return {"log-id": 700}, 200

        def store_local_batch_file(self, **kwargs):
            stored.update(kwargs)
            return 1

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            stored["finish"] = kwargs
            return True

    monkeypatch.setattr(batch_local, "DBManager", _MidChunkDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    result = asyncio.run(
        batch_local.run_local_batch(
            {
                "id": 2005,
                "upstream_id": "batch_m",
                "input_file_id": "file-in",
                "api_key_id": 11,
                "team_id": OWN_TEAM,
                "user_id": 13,
                "status": "in_progress",
            }
        )
    )

    assert result is None
    assert executed == []  # the lines were cancelled before they finished
    assert "checkpoints" not in stored
    assert "finish" not in stored
    assert "content" not in stored


class _LineLogDB:
    """The minimum of a database a single line needs: its usage-log row."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def log_usage(self, **kwargs):
        return {"log-id": 600}, 200


def test_a_failing_line_is_reported_without_stopping_the_batch(monkeypatch):
    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        if body.get("custom") == "boom":
            raise RuntimeError("upstream exploded")
        return {"status_code": 400, "data": {"error": {"message": "context length exceeded"}}}

    monkeypatch.setattr(batch_local, "DBManager", _LineLogDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    row, failed = asyncio.run(batch_local._run_line(_local_line("a"), _auth(), {}, asyncio.Semaphore(1)))

    assert failed is True
    assert row["error"]["code"] == "400"
    assert "context length" in row["error"]["message"]


def test_a_line_without_a_log_row_is_refused_not_run_unbilled(monkeypatch):
    # Without the log row the pipeline would run the request and bill nothing,
    # so the line is refused instead of run — the batch reports it as failed.
    executed = []

    async def fake_execute(path, headers, body, client_ip, auth, log_id):
        executed.append(body)
        return {"status_code": 200, "data": {}}

    class _BrokenLogDB(_LineLogDB):
        def log_usage(self, **kwargs):
            raise RuntimeError("the ledger is down")

    monkeypatch.setattr(batch_local, "DBManager", _BrokenLogDB)
    monkeypatch.setitem(__import__("sys").modules, "logos.main", main)
    monkeypatch.setattr(main, "execute_proxy_job", fake_execute, raising=False)

    row, failed = asyncio.run(batch_local._run_line(_local_line("a"), _auth(), {}, asyncio.Semaphore(1)))

    assert failed is True
    assert row["response"]["status_code"] == 500
    assert "could not be started" in row["error"]["message"]
    assert executed == []  # no unbilled request may reach the provider


def test_a_local_batch_object_looks_like_a_providers(monkeypatch):
    # A polling script must not be able to tell the two apart, or chaining one
    # batch onto the last would need two clients.
    now = datetime.now(timezone.utc)
    rendered = batch_local.local_batch_object(
        {
            "upstream_id": "batch_x",
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-in",
            "completion_window": "24h",
            "status": "completed",
            "output_file_id": "file-out",
            "created_at": now,
            "started_at": now,
            "finished_at": now,
            "total_requests": 3,
            "completed_requests": 2,
            "failed_requests": 1,
            "request_metadata": {"run": "bench"},
        }
    )

    assert rendered["object"] == "batch"
    assert rendered["status"] == "completed"
    assert rendered["output_file_id"] == "file-out"
    assert rendered["request_counts"] == {"total": 3, "completed": 2, "failed": 1}
    assert rendered["completed_at"] == int(now.timestamp())
    assert rendered["metadata"] == {"run": "bench"}


def test_a_cancel_before_the_runner_started_still_finishes_the_batch(monkeypatch):
    # The cancel moves a queued batch to 'cancelling'; without the runner
    # picking that state up it would sit there forever. 'cancelling' goes
    # through the same lease claim as every other state: the claim is what
    # makes the takeover exclusive, and the pending cancel is read off the
    # first progress write.
    claimed = []
    finished = {}

    class _CancelDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, object_id, runner_id, lease_seconds):
            claimed.append(object_id)
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return {"id": 1000}

        def get_local_batch_file_content(self, object_id):
            return _jsonl(_local_line("a"))

        def get_api_key_by_id(self, api_key_id):
            return {
                "id": 11,
                "key_value": "lg-test",
                "name": "k",
                "key_type": "user",
                "team_id": OWN_TEAM,
                "user_id": 13,
                "environment": "test",
                "log": "BILLING",
                "settings": {},
                "default_priority": 1,
            }

        def get_local_batch_lines(self, object_id):
            return {}

        def update_local_batch_progress(self, object_id, runner_id, completed, failed, lease_seconds):
            return True  # a cancel is pending

        def store_local_batch_file(self, **kwargs):
            return 1

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            finished.update(kwargs)
            return True

    monkeypatch.setattr(batch_local, "DBManager", _CancelDB)

    asyncio.run(
        batch_local.run_local_batch(
            {
                "id": 2001,
                "upstream_id": "batch_c",
                "input_file_id": "file-in",
                "api_key_id": 11,
                "team_id": OWN_TEAM,
                "user_id": 13,
                "status": "cancelling",
            }
        )
    )

    assert claimed == [2001]  # taken over like any other queued batch
    assert finished["status"] == "cancelled"
    assert finished["completed"] == 0


def test_a_batch_already_running_here_is_not_started_again(monkeypatch):
    # The runner loop re-offers in_progress rows (so a batch interrupted by a
    # restart resumes), which would otherwise start a second run of one this
    # process is already working through.
    claimed = []

    class _ClaimDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def claim_local_batch(self, object_id, runner_id, lease_seconds):
            claimed.append(object_id)
            return True

        def get_local_object_by_upstream_id(self, kind, upstream_id):
            return None

        def get_local_batch_file_content(self, object_id):
            return None

        def finish_local_batch(self, object_id, runner_id, **kwargs):
            pass

    monkeypatch.setattr(batch_local, "DBManager", _ClaimDB)
    row = {
        "id": 2002,
        "upstream_id": "batch_d",
        "input_file_id": "file-in",
        "api_key_id": 11,
        "team_id": OWN_TEAM,
        "user_id": 13,
        "status": "validating",
    }

    batch_local._running.add(2002)
    try:
        assert asyncio.run(batch_local.run_local_batch(row)) is None
        assert claimed == []  # it never reached the database claim
    finally:
        batch_local._running.discard(2002)

    # With the guard clear it runs — and the claim is what decides across
    # processes.
    asyncio.run(batch_local.run_local_batch(row))
    assert claimed == [2002]
