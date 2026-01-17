import pytest

import logos.main as main


class DummyResponse:
    def __init__(self, status_code=200, content=None):
        self.status_code = status_code
        self.content = content or {}


@pytest.mark.asyncio
async def test_route_and_execute_no_models_sync():
    with pytest.raises(main.HTTPException) as exc:
        await main.route_and_execute([], {}, {}, "lg-key", "chat/completions", log_id=None, is_async_job=False)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_route_and_execute_proxy_branch(monkeypatch):
    called = {}

    async def fake_proxy(body, headers, logos_key, path, log_id, is_async_job):
        called["args"] = (body, headers, logos_key, path, log_id, is_async_job)
        return {"status": "proxy"}

    monkeypatch.setattr(main, "_execute_proxy_mode", fake_proxy)

    out = await main.route_and_execute(
        models=[{"id": 1}],
        body={"model": "gpt-4o"},
        headers={"h": "v"},
        logos_key="lg-key",
        path="chat/completions",
        log_id=1,
        is_async_job=False,
    )
    assert out == {"status": "proxy"}
    assert called["args"][-1] is False


@pytest.mark.asyncio
async def test_route_and_execute_resource_branch(monkeypatch):
    called = {}

    async def fake_resource(models, body, headers, logos_key, path, log_id, is_async_job):
        called["args"] = (models, body, headers, logos_key, path, log_id, is_async_job)
        return {"status": "resource"}

    monkeypatch.setattr(main, "_execute_resource_mode", fake_resource)

    out = await main.route_and_execute(
        models=[{"id": 1}],
        body={},
        headers={"h": "v"},
        logos_key="lg-key",
        path="chat/completions",
        log_id=1,
        is_async_job=True,
    )
    assert out == {"status": "resource"}
    assert called["args"][-1] is True
