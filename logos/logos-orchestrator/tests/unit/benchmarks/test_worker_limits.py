import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from logos.benchmarks.configuration import ServingOverrides
from logos.benchmarks.worker_limits import validate_worker_overrides, worker_limits


def snapshot(count=2, selector="all"):
    return {
        "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "first_status_received": True,
        "runtime": {
            "gpu_devices": selector,
            "devices": {
                "nvidia_smi_available": True,
                "devices": [{"kind": "nvidia", "memory_total_mb": 24000} for _ in range(count)],
            },
            "lanes": [{"model": "m", "lane_config": {"vllm_config": {"tensor_parallel_size": 1}}}],
        },
    }


@pytest.mark.parametrize("count,tp,pp", [(2, 1, 1), (2, 2, 1), (2, 1, 2), (3, 3, 1)])
def test_parallelism_within_live_worker_gpu_count(count, tp, pp):
    validate_worker_overrides(
        ServingOverrides(tensor_parallel_size=tp, pipeline_parallel_size=pp), worker_limits(snapshot(count), "m")
    )


@pytest.mark.parametrize("tp,pp", [(38, 1), (3, 1), (2, 2), (1, 3)])
def test_impossible_parallelism_is_rejected(tp, pp):
    with pytest.raises(ValueError, match="only 2 available"):
        validate_worker_overrides(
            ServingOverrides(tensor_parallel_size=tp, pipeline_parallel_size=pp), worker_limits(snapshot(), "m")
        )


def test_limits_respect_worker_and_lane_gpu_assignments():
    status = snapshot(3, "1,2")
    status["runtime"]["lanes"][0]["is_static"] = True
    status["runtime"]["lanes"][0]["lane_config"]["gpu_devices"] = "2"
    assert worker_limits(status, "m")["gpu_count"] == 1


def test_combination_includes_current_settings_when_only_one_field_changes():
    status = snapshot()
    status["runtime"]["lanes"][0]["lane_config"]["vllm_config"]["tensor_parallel_size"] = 2
    with pytest.raises(ValueError, match="requires 4 GPUs"):
        validate_worker_overrides(ServingOverrides(pipeline_parallel_size=2), worker_limits(status, "m"))


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"kv_cache_memory_bytes": "0"}, "greater than zero"),
        ({"kv_cache_memory_bytes": "999G"}, "smaller than its total memory"),
        ({"max_num_seqs": 32, "max_num_batched_tokens": 8}, "at least max sequences"),
    ],
)
def test_known_memory_and_batch_limits(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_worker_overrides(ServingOverrides(**overrides), worker_limits(snapshot(), "m"))


def test_unknown_gpu_inventory_does_not_invent_a_limit():
    limits = worker_limits(None, "m")
    assert limits["gpu_count"] is None
    validate_worker_overrides(ServingOverrides(), limits)
    with pytest.raises(ValueError, match="GPU information is unavailable"):
        validate_worker_overrides(ServingOverrides(tensor_parallel_size=1), limits)


async def test_impossible_benchmark_is_rejected_before_job_creation(monkeypatch):
    import importlib

    main = importlib.import_module("logos.main")

    db = MagicMock()
    db.__enter__.return_value = db
    db.get_model_provider_benchmark_target.return_value = {
        "provider_id": 7,
        "provider_type": "logosnode",
        "provider_name": "two-gpu-worker",
        "model_name": "m",
    }
    db.find_active_model_benchmark_job.return_value = None
    monkeypatch.setattr(main, "DBManager", lambda: db)
    monkeypatch.setattr(main, "_capacity_planner", MagicMock())
    monkeypatch.setattr(main, "_require_internal_secret", lambda _: None)
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = snapshot()
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    monkeypatch.setattr(main, "dataset_metadata", AsyncMock(return_value={"text_columns": ["question"]}))
    with pytest.raises(HTTPException, match="only 2 available") as error:
        await main.internal_run_model_benchmark(
            main._InternalBenchmarkRequest(model_provider_id=31, serving_overrides={"tensor_parallel_size": 38}),
            MagicMock(),
        )
    assert error.value.status_code == 400
    db.create_job_record.assert_not_called()
