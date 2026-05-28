from unittest.mock import MagicMock

import pytest

import logos.main as main


async def test_route_and_execute_no_deployments_sync():
    """route_and_execute raises 404 when deployments list is empty."""
    with pytest.raises(main.HTTPException) as exc:
        await main.route_and_execute(
            deployments=[],
            body={},
            headers={},
            auth=MagicMock(key_value="lg-key"),
            path="chat/completions",
            log_id=None,
            is_async_job=False,
        )
    assert exc.value.status_code == 404


async def test_route_and_execute_no_deployments_async():
    """route_and_execute returns error dict when deployments empty in async mode."""
    result = await main.route_and_execute(
        deployments=[],
        body={},
        headers={},
        auth=MagicMock(key_value="lg-key"),
        path="chat/completions",
        log_id=None,
        is_async_job=True,
    )
    assert result["status_code"] == 404
    assert "error" in result["data"]


async def test_route_and_execute_proxy_branch(monkeypatch):
    """route_and_execute delegates to _execute_proxy_mode when body has 'model'."""
    called = {}

    async def fake_proxy(
        body,
        headers,
        auth,
        deployments,
        log_id,
        is_async_job,
        request_id=None,
        request_path=None,
        priority=1,
    ):
        called["proxy"] = True
        return {"status": "proxy"}

    monkeypatch.setattr(main, "_execute_proxy_mode", fake_proxy)

    out = await main.route_and_execute(
        deployments=[{"model_id": 1, "provider_id": 1}],
        body={"model": "gpt-4o"},
        headers={"h": "v"},
        auth=MagicMock(key_value="lg-key"),
        path="chat/completions",
        log_id=1,
        is_async_job=False,
    )
    assert out == {"status": "proxy"}
    assert called.get("proxy") is True


async def test_route_and_execute_resource_branch(monkeypatch):
    """route_and_execute delegates to _execute_resource_mode when body has no 'model'."""
    called = {}

    async def fake_resource(deployments, body, headers, auth, log_id, is_async_job, **kw):
        called["resource"] = True
        return {"status": "resource"}

    monkeypatch.setattr(main, "_execute_resource_mode", fake_resource)

    out = await main.route_and_execute(
        deployments=[{"model_id": 1, "provider_id": 1}],
        body={},
        headers={"h": "v"},
        auth=MagicMock(key_value="lg-key"),
        path="chat/completions",
        log_id=1,
        is_async_job=True,
    )
    assert out == {"status": "resource"}
    assert called.get("resource") is True
