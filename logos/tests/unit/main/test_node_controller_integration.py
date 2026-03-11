from __future__ import annotations

import asyncio
import base64
from datetime import timedelta

from fastapi import HTTPException, Request
import pytest

from logos.dbutils.dbrequest import NodeControllerAuthRequest, NodeControllerRegisterRequest
from logos.node_controller_registry import (
    NodeControllerOfflineError,
    NodeControllerRuntimeRegistry,
)
from logos.pipeline.context_resolver import ContextResolver
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
    registry = NodeControllerRuntimeRegistry()
    token = await registry.issue_ticket(11, "node-a", ["model-a"])
    ticket = await registry.consume_ticket(token)
    assert ticket is not None

    ws = _FakeWebSocket()
    await registry.attach_session(ticket, ws)
    await registry.update_status(
        provider_id=11,
        status={
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
async def test_registry_command_roundtrip():
    registry = NodeControllerRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(9, "node-x", []))
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
    registry = NodeControllerRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(12, "node-z", []))
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
async def test_registry_stale_session_raises():
    registry = NodeControllerRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(10, "node-y", []))
    assert ticket is not None
    ws = _FakeWebSocket()
    session = await registry.attach_session(ticket, ws)
    session.last_heartbeat = session.last_heartbeat - timedelta(seconds=120)

    with pytest.raises(NodeControllerOfflineError):
        await registry.get_runtime_snapshot(10, stale_after_seconds=1)


@pytest.mark.asyncio
async def test_node_auth_requires_matching_shared_key(monkeypatch):
    monkeypatch.setattr(main_mod, "_node_registry", NodeControllerRuntimeRegistry())

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        @staticmethod
        def get_provider(provider_id: int):
            return {
                "id": provider_id,
                "provider_type": "node",
                "api_key": "shared-secret",
            }

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = NodeControllerAuthRequest(provider_id=3, shared_key="shared-secret", node_id="node-3")
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "method": "POST",
            "path": "/logosdb/providers/node/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    response = await main_mod.node_auth(req, request)
    assert "session_token" in response
    assert response["ws_url"].startswith("wss://logos.local:8080/")

    bad_req = NodeControllerAuthRequest(provider_id=3, shared_key="wrong", node_id="node-3")
    with pytest.raises(HTTPException):
        await main_mod.node_auth(bad_req, request)


@pytest.mark.asyncio
async def test_node_auth_requires_tls(monkeypatch):
    monkeypatch.setattr(main_mod, "_node_registry", NodeControllerRuntimeRegistry())
    req = NodeControllerAuthRequest(provider_id=3, shared_key="secret", node_id="node-3")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": "/logosdb/providers/node/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    with pytest.raises(HTTPException) as exc:
        await main_mod.node_auth(req, request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_node_auth_allows_http_in_dev_mode(monkeypatch):
    monkeypatch.setattr(main_mod, "_node_registry", NodeControllerRuntimeRegistry())
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
                "provider_type": "node",
                "api_key": "shared-secret",
            }

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = NodeControllerAuthRequest(provider_id=3, shared_key="shared-secret", node_id="node-3")
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": "/logosdb/providers/node/auth",
            "headers": [(b"host", b"logos.local:8080")],
        }
    )
    response = await main_mod.node_auth(req, request)
    assert response["ws_url"].startswith("ws://logos.local:8080/")


@pytest.mark.asyncio
async def test_node_register_creates_provider_and_key(monkeypatch):
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
            assert kwargs["provider_type"] == "node"
            assert kwargs["provider_name"] == "gpu-node-1"
            assert kwargs["api_key"]
            return {"provider-id": 41}, 200

    monkeypatch.setattr(main_mod, "DBManager", _FakeDB)

    req = NodeControllerRegisterRequest(
        logos_key="root-key",
        provider_name="gpu-node-1",
    )
    response = await main_mod.node_register(req)
    assert response["provider_id"] == 41
    assert response["provider_type"] == "node"
    assert response["shared_key"]


@pytest.mark.asyncio
async def test_context_resolver_uses_node_lane_selection(monkeypatch):
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
                "provider_name": "node-provider",
                "provider_type": "node",
                "base_url": "https://node.example",
                "auth_name": "Authorization",
                "auth_format": "Bearer {}",
                "api_key": "shared-secret",
            }

    class _FakeRegistry:
        async def select_lane_for_model(self, provider_id: int, model_name: str):  # noqa: ARG002
            return {"lane_id": "lane-7"}

    monkeypatch.setattr("logos.pipeline.context_resolver.DBManager", _FakeDB)
    resolver = ContextResolver(node_registry=_FakeRegistry())
    ctx = await resolver.resolve_context(1, 77)
    assert ctx is not None
    assert ctx.provider_type == "node"
    assert ctx.lane_id == "lane-7"
    assert ctx.forward_url == "node://provider/77/lane/lane-7"

    class _NoLaneRegistry:
        async def select_lane_for_model(self, provider_id: int, model_name: str):  # noqa: ARG002
            return None

    resolver_no_lane = ContextResolver(node_registry=_NoLaneRegistry())
    assert await resolver_no_lane.resolve_context(1, 77) is None
