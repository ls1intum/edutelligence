import pytest

import logos.main as main


@pytest.mark.asyncio
async def test_execute_proxy_mode_streaming_calls_stream(monkeypatch):
    called = {}

    def fake_behaviour(headers, providers, path):
        return {"Authorization": "Bearer x"}, "http://upstream", 1

    def fake_stream(url, headers, body, log_id, provider_id, model_id, policy_id, classified):
        called["args"] = (url, headers, body, log_id, provider_id, model_id, policy_id, classified)
        return {"streamed": True}

    monkeypatch.setattr(main, "proxy_behaviour", fake_behaviour)
    monkeypatch.setattr(main, "_proxy_streaming_response", fake_stream)
    monkeypatch.setattr(main, "_proxy_sync_response", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should stream")))

    # Dummy DB
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_providers(self, logos_key):
            return [{"id": 1, "name": "azure", "base_url": "https://example.com"}]

        def get_provider(self, provider):
            if isinstance(provider, dict):
                return provider
            return {"id": provider, "name": "azure", "base_url": "https://example.com"}

    monkeypatch.setattr(main, "DBManager", DummyDB)

    out = await main._execute_proxy_mode(
        body={"model": "gpt-4o", "stream": True},
        headers={"Authorization": "Bearer x"},
        logos_key="lg-key",
        path="chat/completions",
        log_id=None,
        is_async_job=False,
    )
    assert out["streamed"] is True
    assert called["args"][0].startswith("http://upstream")


@pytest.mark.asyncio
async def test_execute_resource_mode_failure_records_error(monkeypatch):
    class Result:
        success = False
        error = "boom"
        execution_context = None
        provider_id = None
        model_id = None
        classification_stats = {}
        scheduling_stats = {"request_id": "req-1"}

    async def fake_process(req):
        return Result()

    monkeypatch.setattr(
        main,
        "_pipeline",
        type("P", (), {"process": fake_process, "record_completion": lambda *a, **k: None}),
        raising=False,
    )
    monkeypatch.setattr(main, "_extract_policy", lambda headers, logos_key, body: {"p": "ok"})

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            models=[{"id": 10}],
            body={},
            headers={"h": "v"},
            logos_key="lg-test",
            path="chat/completions",
            log_id=1,
            is_async_job=False,
        )
    assert exc.value.status_code == 503
