from __future__ import annotations

from fastapi import FastAPI
import pytest
from httpx import ASGITransport, AsyncClient

import node_controller.config as config_mod
from node_controller.models import AppConfig, ControllerConfig
from node_controller.relay_api import router as relay_router


def _build_app(tmp_path) -> FastAPI:
    config_mod._config = AppConfig(  # noqa: SLF001
        controller=ControllerConfig(api_key="relay-secret")
    )
    config_mod._config_path = None  # noqa: SLF001

    app = FastAPI()
    app.include_router(relay_router)
    return app


@pytest.mark.asyncio
async def test_relay_endpoint_is_deprecated_and_disabled(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post(
            "/relay/lanes/lane-a/infer",
            headers={"Authorization": "Bearer relay-secret"},
            json={"stream": False},
        )
    assert resp.status_code == 410
    assert "deprecated" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_relay_endpoint_requires_auth(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/relay/lanes/lane-a/infer", json={"stream": False})
    assert resp.status_code == 401
