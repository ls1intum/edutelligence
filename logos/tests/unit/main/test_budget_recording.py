from __future__ import annotations

from types import SimpleNamespace

import pytest

import logos.main as main
from logos.pipeline.executor import ExecutionResult


def _make_budget_db(cost_to_return: int = 300):
    class BudgetDB:
        budget_calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_time_at_first_token(self, log_id):
            pass

        def set_response_payload(self, *args, **kwargs):
            pass

        def compute_cost_micro_cents(self, usage_tokens):
            return cost_to_return

        def record_budget_usage(self, api_key_id, month_start, cost_micro_cents):
            self.budget_calls.append((api_key_id, month_start, cost_micro_cents))

    return BudgetDB


def _make_pipeline(sync_result):
    class DummyExecutor:
        async def execute_sync(self, url, headers, payload):
            return sync_result

    class DummyScheduler:
        def release(self, *args):
            pass

    class DummyPipeline:
        executor = DummyExecutor()
        scheduler = DummyScheduler()

        @staticmethod
        def update_provider_stats(*args, **kwargs):
            return None

        @staticmethod
        def record_completion(**kwargs):
            pass

    return DummyPipeline()


def _success_result():
    return ExecutionResult(
        success=True,
        response={
            "id": "r1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        },
        error=None,
        usage={},
        is_streaming=False,
        headers=None,
    )


@pytest.mark.asyncio
async def test_budget_recorded_on_successful_sync_request(monkeypatch):
    dummy_db = _make_budget_db(cost_to_return=300)
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_pipeline", _make_pipeline(_success_result()), raising=False)

    await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"messages": [{"role": "user", "content": "hi"}]},
        log_id=99,
        provider_id=1,
        model_id=10,
        policy_id=-1,
        classification_stats={},
        scheduling_stats={
            "request_id": "req-budget",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.0,
            "is_cold_start": False,
        },
        api_key_id=42,
    )

    assert len(dummy_db.budget_calls) == 1, "record_budget_usage should be called once"
    api_key_id, month_start, cost = dummy_db.budget_calls[0]
    assert api_key_id == 42
    assert cost == 300
    assert month_start.endswith("-01")  # first day of month


@pytest.mark.asyncio
async def test_budget_not_recorded_when_cost_is_zero(monkeypatch):
    dummy_db = _make_budget_db(cost_to_return=0)
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_pipeline", _make_pipeline(_success_result()), raising=False)

    await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"messages": [{"role": "user", "content": "hi"}]},
        log_id=99,
        provider_id=1,
        model_id=10,
        policy_id=-1,
        classification_stats={},
        scheduling_stats={
            "request_id": "req-budget-zero",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.0,
            "is_cold_start": False,
        },
        api_key_id=42,
    )

    assert dummy_db.budget_calls == [], "should not write 0-cost rows"


@pytest.mark.asyncio
async def test_budget_not_recorded_when_api_key_id_is_none(monkeypatch):
    dummy_db = _make_budget_db(cost_to_return=300)
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_pipeline", _make_pipeline(_success_result()), raising=False)

    await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"messages": [{"role": "user", "content": "hi"}]},
        log_id=99,
        provider_id=1,
        model_id=10,
        policy_id=-1,
        classification_stats={},
        scheduling_stats={
            "request_id": "req-no-key",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.0,
            "is_cold_start": False,
        },
        api_key_id=None,
    )

    assert dummy_db.budget_calls == [], "should not write when api_key_id is None"
