import pytest

import logos.main as main


async def test_execute_proxy_mode_requires_model_in_body(monkeypatch):
    """_execute_proxy_mode raises 400 when body has no 'model' key."""
    # Stub DBManager so no real DB call is attempted
    class DummyDB:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main, "DBManager", DummyDB)

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_proxy_mode(
            body={"stream": True},          # no "model" key
            headers={"Authorization": "Bearer x"},
            logos_key="lg-key",
            deployments=[{"model_id": 1, "provider_id": 1}],
            log_id=None,
            is_async_job=False,
        )
    assert exc.value.status_code == 400


async def test_execute_resource_mode_failure_records_error(monkeypatch):
    """_execute_resource_mode returns 503 when the pipeline fails."""

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
            deployments=[{"model_id": 10, "provider_id": 1}],
            body={},
            headers={"h": "v"},
            logos_key="lg-test",
            log_id=1,
            is_async_job=False,
        )
    assert exc.value.status_code == 503
