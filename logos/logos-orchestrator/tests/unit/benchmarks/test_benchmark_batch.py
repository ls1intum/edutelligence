import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from logos.benchmarks.batch_runner import run_benchmark_batch
from logos.benchmarks.configuration import BenchmarkBatch


def test_batch_validates_all_configurations_and_total_size():
    assert BenchmarkBatch(configurations=[{}], repetitions=100).repetitions == 100
    for plan in [
        {"configurations": []},
        {"configurations": [{}], "repetitions": 0},
        {"configurations": [{}, {}], "repetitions": 6000},
        {"configurations": [{"concurrency": 33}]},
        {"configurations": [{"serving_overrides": {"tensor_parallel_size": 2}}, {}]},
    ]:
        with pytest.raises(ValidationError):
            BenchmarkBatch(**plan)


async def test_batch_runs_sequentially_with_one_final_completion():
    batch = BenchmarkBatch(configurations=[{"concurrency": 1}, {"concurrency": 4}], repetitions=10)
    calls = []

    async def execute(settings, progress, finalize):
        calls.append((settings.concurrency, progress.copy(), finalize))
        await asyncio.sleep(0)
        return len(calls)

    await run_benchmark_batch(batch, execute)
    assert len(calls) == 20
    assert [call[0] for call in calls] == [1] * 10 + [4] * 10
    assert [call[1]["completed_runs"] for call in calls] == list(range(20))
    assert all(call[1]["total_runs"] == 20 for call in calls)
    assert [call[2] for call in calls] == [False] * 19 + [True]


async def test_failed_run_stops_batch_and_cancellation_propagates():
    batch = BenchmarkBatch(configurations=[{}], repetitions=20)
    execute = AsyncMock(side_effect=[11, None])
    await run_benchmark_batch(batch, execute)
    assert execute.await_count == 2
    execute = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await run_benchmark_batch(batch, execute)
    assert execute.await_count == 1


@pytest.mark.parametrize("finalize", [False, True])
async def test_runner_keeps_provider_lease_between_runs(monkeypatch, finalize):
    import importlib

    runner = importlib.import_module("logos.benchmarks.guidellm_runner")
    db = MagicMock()
    db.__enter__.return_value = db
    db.insert_model_provider_benchmark.return_value = 123
    monkeypatch.setattr(importlib.import_module("logos.dbutils.dbmanager"), "DBManager", lambda: db)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/bin/guidellm")
    monkeypatch.setattr(runner, "send_warmup_request", AsyncMock())

    async def subprocess(*args, **kwargs):
        # The report is adjacent to the scenario, as for the real subprocess.
        runner.Path(args[-1]).with_name("benchmarks.json").write_text(
            json.dumps(
                {
                    "benchmarks": [
                        {
                            "config": {},
                            "metrics": {"request_totals": {"successful": 5, "total": 5, "errored": 0, "incomplete": 0}},
                        }
                    ]
                }
            )
        )
        return MagicMock(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", subprocess)
    result = await runner.run_benchmark_job(
        job_id=7,
        model_provider_id=31,
        target="http://127.0.0.1/v1",
        model="m",
        api_key=None,
        samples=5,
        max_output_tokens=32,
        serving_configuration={},
        batch_progress={"run_index": 2, "total_runs": 3, "completed_runs": 1},
        finalize=finalize,
    )
    assert result == 123
    calls = db.update_job_status.call_args_list
    assert all(call.kwargs["result_payload"]["total_runs"] == 3 for call in calls)
    assert calls[-1].args == (7, "success" if finalize else "running")
    assert calls[-1].kwargs["result_payload"]["completed_runs"] == 2


async def test_batch_endpoint_submits_once_and_uses_each_configuration(monkeypatch):
    import importlib

    internal = importlib.import_module("logos.routers.internal")
    main = importlib.import_module("logos.main")
    db = MagicMock()
    db.__enter__.return_value = db
    db.find_active_model_benchmark_job.return_value = None
    db.create_job_record.return_value = 77
    db.get_model_provider_benchmark_target.return_value = {
        "provider_id": 7,
        "provider_type": "cloud",
        "provider_name": "Cloud",
        "model_id": 1,
        "model_name": "m",
        "target": "https://provider.example/v1",
    }
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = None
    monkeypatch.setattr(internal, "DBManager", lambda: db)
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    monkeypatch.setattr(internal, "_require_internal_secret", lambda _: None)
    metadata = AsyncMock(return_value={"text_columns": ["question"]})
    monkeypatch.setattr(internal, "dataset_metadata", metadata)
    runner = AsyncMock(return_value=123)
    monkeypatch.setattr(internal, "run_benchmark_job", runner)
    response = await internal.internal_run_model_benchmark(
        internal.InternalBenchmarkRequest(
            model_provider_id=31,
            batch={
                "configurations": [{"concurrency": 4, "samples": 5}, {"concurrency": 8, "samples": 10}],
                "repetitions": 2,
            },
        ),
        MagicMock(),
    )
    await main._benchmark_tasks_by_job[77]
    assert response.status_code == 202
    db.create_job_record.assert_called_once()
    metadata.assert_awaited_once()
    assert [call.kwargs["settings"].concurrency for call in runner.await_args_list] == [4, 4, 8, 8]
    assert [call.kwargs["samples"] for call in runner.await_args_list] == [5, 5, 10, 10]
    assert [call.kwargs["finalize"] for call in runner.await_args_list] == [False, False, False, True]
