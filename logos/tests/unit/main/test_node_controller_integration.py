from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
import pytest

from logos.dbutils.dbrequest import ConnectModelProviderRequest, LogosNodeAuthRequest, LogosNodeRegisterRequest
from logos.logosnode_registry import (
    LogosNodeOfflineError,
    LogosNodeSessionConflictError,
    LogosNodeRuntimeRegistry,
)
from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
import logos.main as main_mod


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_registry_selects_least_active_lane():
    registry = LogosNodeRuntimeRegistry()
    token = await registry.issue_ticket(11, "worker-a", ["model-a"])
    ticket = await registry.consume_ticket(token)
    assert ticket is not None

    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)
    await registry.update_runtime(
        provider_id=11,
        runtime={
            "lanes": [
                {"lane_id": "lane-2", "model": "model-a", "runtime_state": "running", "active_requests": 2},
                {"lane_id": "lane-1", "model": "model-a", "runtime_state": "running", "active_requests": 1},
            ]
        },
    )

    selected = await registry.select_lane_for_model(11, "model-a")
    assert selected is not None
    assert selected["lane_id"] == "lane-1"


@pytest.mark.asyncio
async def test_registry_prefers_lane_with_lower_vllm_queue_pressure():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(16, "worker-qwen", ["model-a"]))
    assert ticket is not None

    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)
    await registry.update_runtime(
        provider_id=16,
        runtime={
            "lanes": [
                {
                    "lane_id": "lane-busy",
                    "model": "model-a",
                    "runtime_state": "running",
                    "active_requests": 1,
                    "effective_vram_mb": 16000,
                    "backend_metrics": {
                        "queue_waiting": 5,
                        "requests_running": 2,
                        "ttft_histogram": {"0.5": 2, "1.0": 6},
                    },
                },
                {
                    "lane_id": "lane-cool",
                    "model": "model-a",
                    "runtime_state": "running",
                    "active_requests": 1,
                    "effective_vram_mb": 12000,
                    "backend_metrics": {
                        "queue_waiting": 0,
                        "requests_running": 1,
                        "ttft_histogram": {"0.5": 4, "1.0": 4},
                    },
                },
            ]
        },
    )

    selected = await registry.select_lane_for_model(16, "model-a")
    assert selected is not None
    assert selected["lane_id"] == "lane-cool"


@pytest.mark.asyncio
async def test_registry_recent_samples_respect_cursor():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(21, "worker-history", []))
    assert ticket is not None

    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)
    base_ts = datetime.now(timezone.utc)
    await registry.record_runtime_sample(
        21,
        {
            "snapshot_id": 10,
            "timestamp": base_ts.isoformat(),
            "used_vram_mb": 1024,
        },
    )
    await registry.record_runtime_sample(
        21,
        {
            "snapshot_id": 11,
            "timestamp": (base_ts + timedelta(seconds=5)).isoformat(),
            "used_vram_mb": 2048,
        },
    )

    assert [sample["snapshot_id"] for sample in registry.peek_recent_samples(21, after_snapshot_id=10)] == [11]


@pytest.mark.asyncio
async def test_registry_command_roundtrip():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(9, "worker-x", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)

    task = asyncio.create_task(
        registry.send_command(9, "get_status", {}, timeout_seconds=3)
    )
    await asyncio.sleep(0)
    assert len(ws.sent) == 1
    cmd_id = ws.sent[0]["cmd_id"]
    await registry.on_command_result(9, {"cmd_id": cmd_id, "success": True, "result": {"ok": True}})
    result = await task
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_registry_stream_roundtrip():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(12, "worker-z", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)

    async def _collect():
        chunks = []
        async for chunk in registry.send_stream_command(12, "infer_stream", {}, timeout_seconds=3):
            chunks.append(chunk)
        return chunks

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0)
    assert len(ws.sent) == 1
    cmd_id = ws.sent[0]["cmd_id"]

    await registry.on_stream_start(12, {"cmd_id": cmd_id, "type": "stream_start"})
    await registry.on_stream_chunk(
        12,
        {
            "cmd_id": cmd_id,
            "type": "stream_chunk",
            "chunk_b64": base64.b64encode(b"data: hello\n").decode("ascii"),
        },
    )
    await registry.on_stream_end(12, {"cmd_id": cmd_id, "type": "stream_end", "success": True})
    chunks = await task
    assert chunks == [b"data: hello\n"]


@pytest.mark.asyncio
async def test_registry_parallel_command_roundtrip_out_of_order():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(13, "worker-parallel", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)

    task_a = asyncio.create_task(registry.send_command(13, "cmd-a", {"request": "a"}, timeout_seconds=3))
    task_b = asyncio.create_task(registry.send_command(13, "cmd-b", {"request": "b"}, timeout_seconds=3))

    await asyncio.sleep(0)
    assert len(ws.sent) == 2
    sent_by_action = {payload["action"]: payload for payload in ws.sent}

    await registry.on_command_result(
        13,
        {
            "cmd_id": sent_by_action["cmd-b"]["cmd_id"],
            "success": True,
            "result": {"request": "b", "ok": True},
        },
    )
    await registry.on_command_result(
        13,
        {
            "cmd_id": sent_by_action["cmd-a"]["cmd_id"],
            "success": True,
            "result": {"request": "a", "ok": True},
        },
    )

    result_a, result_b = await asyncio.gather(task_a, task_b)
    assert result_a == {"request": "a", "ok": True}
    assert result_b == {"request": "b", "ok": True}


@pytest.mark.asyncio
async def test_registry_parallel_stream_roundtrip_is_isolated():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(14, "worker-streams", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)

    async def _collect(tag: str):
        chunks = []
        async for chunk in registry.send_stream_command(14, "infer_stream", {"request": tag}, timeout_seconds=3):
            chunks.append(chunk)
        return chunks

    task_a = asyncio.create_task(_collect("a"))
    task_b = asyncio.create_task(_collect("b"))

    await asyncio.sleep(0)
    assert len(ws.sent) == 2
    sent_by_request = {payload["params"]["request"]: payload for payload in ws.sent}
    cmd_a = sent_by_request["a"]["cmd_id"]
    cmd_b = sent_by_request["b"]["cmd_id"]

    await registry.on_stream_start(14, {"cmd_id": cmd_b, "type": "stream_start"})
    await registry.on_stream_start(14, {"cmd_id": cmd_a, "type": "stream_start"})
    await registry.on_stream_chunk(
        14,
        {"cmd_id": cmd_b, "type": "stream_chunk", "chunk_b64": base64.b64encode(b"b-1").decode("ascii")},
    )
    await registry.on_stream_chunk(
        14,
        {"cmd_id": cmd_a, "type": "stream_chunk", "chunk_b64": base64.b64encode(b"a-1").decode("ascii")},
    )
    await registry.on_stream_chunk(
        14,
        {"cmd_id": cmd_b, "type": "stream_chunk", "chunk_b64": base64.b64encode(b"b-2").decode("ascii")},
    )
    await registry.on_stream_end(14, {"cmd_id": cmd_b, "type": "stream_end", "success": True})
    await registry.on_stream_end(14, {"cmd_id": cmd_a, "type": "stream_end", "success": True})

    chunks_a, chunks_b = await asyncio.gather(task_a, task_b)
    assert chunks_a == [b"a-1"]
    assert chunks_b == [b"b-1", b"b-2"]


@pytest.mark.asyncio
async def test_registry_stale_session_raises():
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(10, "worker-y", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    session = await registry.attach_session(ticket, ws)
    session.last_heartbeat = session.last_heartbeat - timedelta(seconds=120)

    with pytest.raises(LogosNodeOfflineError):
        await registry.get_runtime_snapshot(10, stale_after_seconds=1)


@pytest.mark.asyncio
async def test_registry_rejects_different_worker_for_active_provider():
    registry = LogosNodeRuntimeRegistry()
    ticket_a = await registry.consume_ticket(await registry.issue_ticket(15, "worker-a", []))
    ticket_b = await registry.consume_ticket(await registry.issue_ticket(15, "worker-b", []))
    assert ticket_a is not None
    assert ticket_b is not None

    await registry.attach_session(ticket_a, _FakeWebSocket())

    with pytest.raises(LogosNodeSessionConflictError):
        await registry.attach_session(ticket_b, _FakeWebSocket())


@pytest.mark.asyncio
async def test_logosnode_auth_requires_matching_shared_key(monkeypatch):
    monkeypatch.setattr(main_mod, "_logosnode_registry", LogosNodeRuntimeRegistry())

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_provider(provider_id: int):
            return {
                "id": provider_id,
                "provider_type": "logosnode",
                "api_key": "shared-secret",
            }

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = LogosNodeAuthRequest(provider_id=3, shared_key="shared-secret", worker_id="worker-3")
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "method": "POST",
            "path": "/logosdb/providers/logosnode/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    response = await main_mod.logosnode_auth(req, request)
    assert "session_token" in response
    assert response["ws_url"].startswith("wss://logos.local:8080/")

    bad_req = LogosNodeAuthRequest(provider_id=3, shared_key="wrong", worker_id="worker-3")
    with pytest.raises(HTTPException):
        await main_mod.logosnode_auth(bad_req, request)


@pytest.mark.asyncio
async def test_logosnode_auth_rejects_different_active_worker(monkeypatch):
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(3, "worker-a", []))
    assert ticket is not None
    await registry.attach_session(ticket, _FakeWebSocket())
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_provider(provider_id: int):
            return {
                "id": provider_id,
                "provider_type": "logosnode",
                "api_key": "shared-secret",
            }

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = LogosNodeAuthRequest(provider_id=3, shared_key="shared-secret", worker_id="worker-b")
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "method": "POST",
            "path": "/logosdb/providers/logosnode/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )

    with pytest.raises(HTTPException) as exc:
        await main_mod.logosnode_auth(req, request)
    assert exc.value.status_code == 409
    assert "worker-a" in exc.value.detail


@pytest.mark.asyncio
async def test_logosnode_auth_requires_tls(monkeypatch):
    monkeypatch.setattr(main_mod, "_logosnode_registry", LogosNodeRuntimeRegistry())
    req = LogosNodeAuthRequest(provider_id=3, shared_key="secret", worker_id="worker-3")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": "/logosdb/providers/logosnode/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    with pytest.raises(HTTPException) as exc:
        await main_mod.logosnode_auth(req, request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_logosnode_auth_allows_http_in_dev_mode(monkeypatch):
    monkeypatch.setattr(main_mod, "_logosnode_registry", LogosNodeRuntimeRegistry())
    monkeypatch.setenv("LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP", "true")

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_provider(provider_id: int):
            return {
                "id": provider_id,
                "provider_type": "logosnode",
                "api_key": "shared-secret",
            }

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = LogosNodeAuthRequest(provider_id=3, shared_key="shared-secret", worker_id="worker-3")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": "/logosdb/providers/logosnode/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    response = await main_mod.logosnode_auth(req, request)
    assert response["ws_url"].startswith("ws://logos.local:8080/")


@pytest.mark.asyncio
async def test_logosnode_register_creates_provider_and_key(monkeypatch):
    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def check_authorization(logos_key: str) -> bool:
            return logos_key == "root-key"

        @staticmethod
        def add_provider(**kwargs):
            assert kwargs["provider_type"] == "logosnode"
            assert kwargs["provider_name"] == "gpu-node-1"
            assert kwargs["api_key"]
            return {"provider-id": 41}, 200

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = LogosNodeRegisterRequest(
        logos_key="root-key",
        provider_name="gpu-node-1",
    )
    response = await main_mod.logosnode_register(req)
    assert response["provider_id"] == 41
    assert response["provider_type"] == "logosnode"
    assert response["shared_key"]


@pytest.mark.asyncio
async def test_refresh_pipeline_runtime_state_reloads_registrations(monkeypatch):
    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_all_deployments():
            return [
                {"model_id": 30, "provider_id": 13, "type": "logosnode"},
                {"model_id": 10, "provider_id": 1, "type": "azure"},
            ]

        @staticmethod
        def get_model(model_id: int):
            return {
                30: {"id": 30, "name": "Qwen/Qwen2.5-Coder-7B-Instruct"},
                10: {"id": 10, "name": "azure-gpt-4-omni"},
            }[model_id]

        @staticmethod
        def get_provider(provider_id: int):
            return {
                13: {"id": 13, "name": "hochbruegge-node", "base_url": ""},
                1: {"id": 1, "name": "azure", "base_url": "https://azure.example"},
            }[provider_id]

        @staticmethod
        def get_provider_config(provider_id: int):
            if provider_id == 13:
                return {"total_vram_mb": 32768}
            return {}

        @staticmethod
        def get_endpoint_for_deployment(model_id: int, provider_id: int):  # noqa: ARG002
            return "https://azure.example/openai/deployments/gpt-4o/chat/completions"

    class _FakeLogosNodeFacade:
        def __init__(self):
            self.registrations = None

        def replace_registrations(self, registrations):
            self.registrations = registrations

    class _FakeAzureFacade:
        def __init__(self):
            self.registrations = None

        def replace_registrations(self, registrations):
            self.registrations = registrations

    class _FakeScheduler:
        def __init__(self):
            self.model_registry = None

        def update_model_registry(self, registry):
            self.model_registry = registry

    class _FakePipeline:
        def __init__(self):
            self.scheduler = _FakeScheduler()

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)
    monkeypatch.setattr(main_mod, "_logosnode_facade", _FakeLogosNodeFacade(), raising=False)
    monkeypatch.setattr(main_mod, "_azure_facade", _FakeAzureFacade(), raising=False)
    monkeypatch.setattr(main_mod, "_pipeline", _FakePipeline(), raising=False)

    rebuilt = []

    def _fake_rebuild_classifier():
        rebuilt.append(True)

    monkeypatch.setattr(main_mod, "rebuild_classifier", _fake_rebuild_classifier)

    await main_mod.refresh_pipeline_runtime_state(rebuild_model_classifier=True)

    assert main_mod._logosnode_facade.registrations == [
        {
            "model_id": 30,
            "provider_name": "hochbruegge-node",
            "logosnode_admin_url": "",
            "model_name": "Qwen/Qwen2.5-Coder-7B-Instruct",
            "total_vram_mb": 32768,
            "provider_id": 13,
        }
    ]
    assert main_mod._azure_facade.registrations == [
        {
            "model_id": 10,
            "provider_name": "azure",
            "model_name": "azure-gpt-4-omni",
            "deployment_name": "gpt-4o",
            "provider_id": 1,
        }
    ]
    assert main_mod._pipeline.scheduler.model_registry == {
        (30, 13): "logosnode",
        (10, 1): "azure",
    }
    assert rebuilt == [True]


@pytest.mark.asyncio
async def test_connect_model_provider_refreshes_pipeline_runtime_state(monkeypatch):
    refresh_calls = []

    async def _fake_refresh_pipeline_runtime_state(*, rebuild_model_classifier: bool = False):
        refresh_calls.append(rebuild_model_classifier)

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def connect_model_provider(**kwargs):
            assert kwargs["provider_id"] == 13
            assert kwargs["model_id"] == 30
            return {"result": "ok"}, 200

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)
    monkeypatch.setattr(main_mod, "refresh_pipeline_runtime_state", _fake_refresh_pipeline_runtime_state)

    req = ConnectModelProviderRequest(logos_key="root-key", model_id=30, provider_id=13)
    response = await main_mod.connect_model_provider(req)

    assert response == ({"result": "ok"}, 200)
    assert refresh_calls == [False]


@pytest.mark.asyncio
async def test_update_provider_sdi_config_refreshes_pipeline_runtime_state(monkeypatch):
    refresh_calls = []

    async def _fake_refresh_pipeline_runtime_state(*, rebuild_model_classifier: bool = False):
        refresh_calls.append(rebuild_model_classifier)

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def update_provider_sdi_config(**kwargs):
            assert kwargs["provider_id"] == 13
            assert kwargs["parallel_capacity"] == 16
            return {"result": "ok"}, 200

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)
    monkeypatch.setattr(main_mod, "refresh_pipeline_runtime_state", _fake_refresh_pipeline_runtime_state)

    req = main_mod.UpdateProviderSdiConfigRequest(
        logos_key="root-key",
        provider_id=13,
        parallel_capacity=16,
    )
    response = await main_mod.update_provider_sdi_config(req)

    assert response == ({"result": "ok"}, 200)
    assert refresh_calls == [False]


@pytest.mark.asyncio
async def test_context_resolver_uses_logosnode_lane_selection(monkeypatch):
    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_auth_info_to_deployment(model_id: int, provider_id: int, profile_id=None):  # noqa: ARG002
            return {
                "model_id": model_id,
                "model_name": "model-a",
                "endpoint": "",
                "provider_id": provider_id,
                "provider_name": "logosnode-provider",
                "provider_type": "logosnode",
                "base_url": "https://node.example",
                "auth_name": "Authorization",
                "auth_format": "Bearer {}",
                "api_key": "shared-secret",
            }

    class _FakeRegistry:
        async def select_lane_for_model(self, provider_id: int, model_name: str):  # noqa: ARG002
            return {"lane_id": "lane-7"}

    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", _FakeDB)
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())
    ctx = await resolver.resolve_context(1, 77)
    assert ctx is not None
    assert ctx.provider_type == "logosnode"
    assert ctx.lane_id == "lane-7"
    assert ctx.forward_url == "logosnode://provider/77/lane/lane-7"

    class _NoLaneRegistry:
        async def select_lane_for_model(self, provider_id: int, model_name: str):  # noqa: ARG002
            return None

    resolver_no_lane = ContextResolver(logosnode_registry=_NoLaneRegistry())
    ctx_no_lane = await resolver_no_lane.resolve_context(1, 77)
    assert ctx_no_lane is not None
    assert ctx_no_lane.forward_url == "https://node.example/"


@pytest.mark.asyncio
async def test_context_resolver_allows_logosnode_without_api_key(monkeypatch):
    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_auth_info_to_deployment(model_id: int, provider_id: int, profile_id=None):  # noqa: ARG002
            return {
                "model_id": model_id,
                "model_name": "model-a",
                "endpoint": "",
                "provider_id": provider_id,
                "provider_name": "logosnode-provider",
                "provider_type": "logosnode",
                "base_url": "https://node.example",
                "auth_name": "Authorization",
                "auth_format": "Bearer {}",
                "api_key": "",
            }

    class _FakeRegistry:
        async def select_lane_for_model(self, provider_id: int, model_name: str):  # noqa: ARG002
            return {"lane_id": "lane-9"}

    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", _FakeDB)
    resolver = ContextResolver(logosnode_registry=_FakeRegistry())
    ctx = await resolver.resolve_context(1, 88)
    assert ctx is not None
    assert ctx.provider_type == "logosnode"
    assert ctx.lane_id == "lane-9"
    assert ctx.forward_url == "logosnode://provider/88/lane/lane-9"


@pytest.mark.asyncio
async def test_sync_response_falls_back_to_direct_http_for_logosnode_without_lane(monkeypatch):
    class _FakeExecutor:
        @staticmethod
        async def execute_sync(forward_url, headers, payload):  # noqa: ARG002
            return main_mod.ExecutionResult(
                success=True,
                response={"ok": True},
                error=None,
                usage={},
                is_streaming=False,
                headers=None,
            )

    class _FakePipeline:
        executor = _FakeExecutor()

        @staticmethod
        def update_provider_stats(model_id, provider_id, headers):  # noqa: ARG002
            return None

        @staticmethod
        def record_completion(**kwargs):  # noqa: ARG002
            return None

        class scheduler:
            @staticmethod
            def release(model_id, provider_id, provider_type, request_id):  # noqa: ARG002
                return None

    monkeypatch.setattr(main_mod, "_pipeline", _FakePipeline(), raising=False)
    monkeypatch.setattr(main_mod, "_context_resolver", ContextResolver(), raising=False)

    context = ExecutionContext(
        model_id=1,
        provider_id=77,
        provider_name="logosnode-provider",
        provider_type="logosnode",
        forward_url="https://node.example/v1/chat/completions",
        auth_header="",
        auth_value="",
        model_name="model-a",
        lane_id=None,
    )

    response = await main_mod._sync_response(
        context=context,
        payload={"messages": [{"role": "user", "content": "hi"}]},
        log_id=None,
        provider_id=77,
        model_id=1,
        policy_id=-1,
        classification_stats={},
        scheduling_stats=None,
    )
    assert response.status_code == 200
