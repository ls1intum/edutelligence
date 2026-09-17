"""The context resolver's logosnode fast path (#980).

The request route already fetched the key's deployment list; for a logosnode
target the resolver used to pay a second database roundtrip
(``get_auth_info_to_deployment``) for values that deployment entry already
carries (the lane lookup runs on the provider/model names) or that stay
unused on that branch (endpoint, base URL, auth). Passing the entry as
``deployment_info`` skips the roundtrip; every other shape keeps the DB path.
"""

from types import SimpleNamespace

import pytest

from logos import PipelineRequest, RequestPipeline
from logos.pipeline.context_resolver import ContextResolver, _normalize_provider_type

DeploymentInfo = {"type": "logosnode", "model_id": 1, "provider_id": 7, "model_name": "m-a", "provider_name": "p-a"}


class _RaisingDBManager:
    def __init__(self, *args, **kwargs):
        raise AssertionError("DBManager must not be touched on the fast path")


class _RecordingDBManager:
    def __init__(self, calls):
        self._calls = calls
        calls.append(1)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_auth_info_to_deployment(self, model_id, provider_id):
        return {
            "model_id": model_id,
            "model_name": "db-model",
            "endpoint": "",
            "provider_id": provider_id,
            "provider_name": "db-provider",
            "provider_type": "logosnode",
            "base_url": "https://node.example",
            "auth_name": "",
            "auth_format": "",
            "api_key": "",
        }


class _FakeRegistry:
    async def select_lane_for_model(self, provider_id, model_name):  # noqa: ARG002
        return {"lane_id": f"lane-{model_name}"}


@pytest.mark.asyncio
async def test_logosnode_deployment_info_skips_the_database(monkeypatch):
    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", _RaisingDBManager)
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())

    ctx = await resolver.resolve_context(1, 7, deployment_info=DeploymentInfo)

    assert ctx is not None
    assert ctx.provider_type == "logosnode"
    assert ctx.model_name == "m-a"
    assert ctx.provider_name == "p-a"
    assert ctx.lane_id == "lane-m-a"
    assert ctx.forward_url == "logosnode://provider/7/lane/lane-m-a"
    # Logosnode lanes receive no credentials — the fast path reproduces the
    # empty auth values the DB path produced for worker registrations.
    assert ctx.auth_header == ""
    assert ctx.auth_value == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("type_spelling", ["logosnode", "node", "node_controller", "logos_worker_node", "LOGOSNODE"])
async def test_all_logosnode_type_spellings_take_the_fast_path(monkeypatch, type_spelling):
    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", _RaisingDBManager)
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())
    deployment_info = dict(DeploymentInfo, type=type_spelling)

    ctx = await resolver.resolve_context(1, 7, deployment_info=deployment_info)

    assert ctx is not None
    assert ctx.provider_type == "logosnode"


@pytest.mark.asyncio
async def test_deployment_info_without_names_falls_back_to_db(monkeypatch):
    calls = []
    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", lambda: _RecordingDBManager(calls))
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())
    deployment_info = dict(DeploymentInfo, model_name=None)

    ctx = await resolver.resolve_context(1, 7, deployment_info=deployment_info)

    assert calls == [1]
    assert ctx is not None
    assert ctx.model_name == "db-model"


@pytest.mark.asyncio
async def test_deployment_info_for_a_cloud_target_falls_back_to_db(monkeypatch):
    calls = []
    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", lambda: _RecordingDBManager(calls))
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())
    deployment_info = dict(DeploymentInfo, type="cloud")

    ctx = await resolver.resolve_context(1, 7, deployment_info=deployment_info)

    assert calls == [1]
    assert ctx is not None
    assert ctx.model_name == "db-model"


@pytest.mark.asyncio
async def test_no_deployment_info_keeps_the_db_path(monkeypatch):
    """Callers without a deployment list (async jobs) resolve as before."""
    calls = []
    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", lambda: _RecordingDBManager(calls))
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())

    ctx = await resolver.resolve_context(1, 7)

    assert calls == [1]
    assert ctx is not None
    assert ctx.model_name == "db-model"


def test_pipeline_passes_the_scheduled_deployment_to_the_resolver():
    request = PipelineRequest(
        payload={},
        headers={},
        allowed_models=[1, 2],
        deployments=[
            {"model_id": 1, "provider_id": 5, "type": "cloud", "model_name": "c", "provider_name": "cp"},
            dict(DeploymentInfo),
        ],
    )
    assert RequestPipeline._scheduled_deployment(request, SimpleNamespace(model_id=1, provider_id=7)) == DeploymentInfo
    # A (model, provider) pair the key's deployment list does not carry.
    assert RequestPipeline._scheduled_deployment(request, SimpleNamespace(model_id=99, provider_id=7)) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("logosnode", "logosnode"),
        ("node", "logosnode"),
        ("node_controller", "logosnode"),
        ("logos_worker_node", "logosnode"),
        ("LOGOSNODE", "logosnode"),
        ("cloud", "cloud"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_provider_type(raw, expected):
    assert _normalize_provider_type(raw) == expected
