import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import logos as main


def _job(*, status="running", provider_id=20, model_id=1, model_name="org/model"):
    return {
        "status": status,
        "environment": "model-provider-benchmark",
        "request_payload": {
            "provider_id": provider_id,
            "model_id": model_id,
            "model_name": model_name,
        },
    }


@pytest.mark.asyncio
async def test_cancel_benchmark_releases_job(monkeypatch):
    request = MagicMock()
    request.headers = {"authorization": "Bearer internal-secret"}
    cancel = MagicMock(return_value=True)
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "_cancel_benchmark_job", cancel)

    response = await main.internal_cancel_model_benchmark(7, request)

    assert response == {"job_id": 7, "status": "failed"}
    cancel.assert_called_once_with(7, "Benchmark cancelled by administrator")


def _install_job_db(monkeypatch, job):
    started = []

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_job(self, job_id):
            assert job_id == 7
            return job

        def record_benchmark_request_started(self, job_id):
            started.append(job_id)

    monkeypatch.setattr(main, "DBManager", DummyDB)
    return started


def _headers(secret="internal-secret", provider_id=20, model="org/model"):
    return main.benchmark_affinity_headers(
        secret=secret,
        job_id=7,
        provider_id=provider_id,
        model=model,
    )


@pytest.mark.asyncio
async def test_worker_benchmark_start_needs_no_provider_endpoint_or_api_key(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_model_provider_benchmark_target(self, model_provider_id):
            assert model_provider_id == 31
            return {
                "model_provider_id": 31,
                "provider_id": 20,
                "provider_name": "basement-worker",
                "provider_type": "logosnode",
                "model_id": 1,
                "model_name": "org/model",
                "target": None,
                "api_key": None,
            }

        def find_active_model_benchmark_job(self, provider_id):
            assert provider_id == 20
            return None

        def lock_model_benchmark_provider(self, provider_id):
            assert provider_id == 20

        def count_active_model_benchmark_jobs(self):
            return 0

        def create_job_record(self, **kwargs):
            return 7

    runner = AsyncMock()
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = {
        "session_id": "session-1",
        "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "first_status_received": True,
        "runtime": {"lanes": []},
    }
    planner = MagicMock()
    planner.prepare_benchmark_lane = AsyncMock(return_value=True)
    request = MagicMock()
    request.headers = {"authorization": "Bearer internal-secret"}

    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "_BENCHMARKS_ENABLED", True)
    monkeypatch.setattr(main, "DBManager", DummyDB)
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    monkeypatch.setattr(main, "_capacity_planner", planner)
    monkeypatch.setattr(main, "run_benchmark_job", runner)

    response = await main.internal_run_model_benchmark(
        main._InternalBenchmarkRequest(model_provider_id=31, samples=15),
        request,
    )
    await asyncio.sleep(0)

    assert response.status_code == 202
    assert runner.await_args.kwargs["target"] == "http://127.0.0.1:8080/internal/model_benchmarks/jobs/7"
    assert runner.await_args.kwargs["api_key"] is None
    assert runner.await_args.kwargs["request_headers"][main.BENCHMARK_PROVIDER_HEADER] == "20"


@pytest.mark.asyncio
async def test_external_benchmark_rejects_api_key_over_plaintext_http(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_model_provider_benchmark_target(self, model_provider_id):
            return {
                "model_provider_id": model_provider_id,
                "provider_id": 20,
                "provider_name": "cloud-provider",
                "provider_type": "cloud",
                "model_id": 1,
                "model_name": "org/model",
                "target": "http://provider.example/v1",
                "api_key": "secret",
            }

    request = MagicMock()
    request.headers = {"authorization": "Bearer internal-secret"}
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "_BENCHMARKS_ENABLED", True)
    monkeypatch.setattr(main, "DBManager", DummyDB)

    with pytest.raises(main.HTTPException) as exc_info:
        await main.internal_run_model_benchmark(
            main._InternalBenchmarkRequest(model_provider_id=31, samples=5),
            request,
        )

    assert exc_info.value.status_code == 409
    assert "HTTPS" in exc_info.value.detail


@pytest.mark.asyncio
async def test_benchmark_start_is_disabled_by_default(monkeypatch):
    request = MagicMock()
    request.headers = {"authorization": "Bearer internal-secret"}
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "_BENCHMARKS_ENABLED", False)

    with pytest.raises(main.HTTPException) as exc_info:
        await main.internal_run_model_benchmark(
            main._InternalBenchmarkRequest(model_provider_id=31),
            request,
        )

    assert exc_info.value.status_code == 503


def test_internal_secret_rejects_non_ascii_token_without_compare_digest_type_error(monkeypatch):
    request = MagicMock()
    request.headers = {"authorization": "Bearer töken"}
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")

    with pytest.raises(main.HTTPException) as exc_info:
        main._require_internal_secret(request)

    assert exc_info.value.status_code == 401


def test_valid_running_job_resolves_required_worker(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    started = _install_job_db(monkeypatch, _job())

    provider_id = main._benchmark_provider_affinity(
        _headers(),
        {"model": "org/model"},
        [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 1, "provider_id": 20, "type": "logosnode"},
        ],
    )

    assert provider_id == 20
    assert started == [7]


def test_worker_session_change_invalidates_benchmark(monkeypatch):
    job = _job()
    job["request_payload"]["provider_session_id"] = "old-session"
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        MagicMock(peek_runtime_snapshot=MagicMock(return_value={"session_id": "new-session"})),
    )
    _install_job_db(monkeypatch, job)

    with pytest.raises(main.HTTPException) as exc_info:
        main._benchmark_provider_affinity(
            _headers(),
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 20, "type": "logosnode"}],
        )

    assert exc_info.value.status_code == 409


def test_warmup_request_does_not_advance_measurement_progress(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    started = _install_job_db(monkeypatch, _job())
    headers = _headers()
    headers[main.BENCHMARK_PHASE_HEADER] = "warmup"

    assert (
        main._benchmark_provider_affinity(
            headers,
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 20, "type": "logosnode"}],
        )
        == 20
    )
    assert started == []


def test_unsigned_public_request_has_no_worker_affinity(monkeypatch):
    monkeypatch.setattr(main, "DBManager", MagicMock(side_effect=AssertionError("DB must not be queried")))

    assert (
        main._benchmark_provider_affinity(
            {"authorization": "Bearer public-key"},
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 10, "type": "logosnode"}],
        )
        is None
    )


def test_forged_affinity_is_rejected_before_job_lookup(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "DBManager", MagicMock(side_effect=AssertionError("DB must not be queried")))
    headers = _headers()
    headers[main.BENCHMARK_PROVIDER_HEADER] = "10"

    with pytest.raises(main.HTTPException) as exc_info:
        main._benchmark_provider_affinity(
            headers,
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 10, "type": "logosnode"}],
        )

    assert exc_info.value.status_code == 401


def test_non_ascii_forged_affinity_is_rejected_without_compare_digest_type_error(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    monkeypatch.setattr(main, "DBManager", MagicMock(side_effect=AssertionError("DB must not be queried")))
    headers = _headers()
    headers[main.BENCHMARK_TOKEN_HEADER] = "töken"

    with pytest.raises(main.HTTPException) as exc_info:
        main._benchmark_provider_affinity(
            headers,
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 20, "type": "logosnode"}],
        )

    assert exc_info.value.status_code == 401


def test_completed_job_token_cannot_be_replayed(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    _install_job_db(monkeypatch, _job(status="success"))

    with pytest.raises(main.HTTPException) as exc_info:
        main._benchmark_provider_affinity(
            _headers(),
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 20, "type": "logosnode"}],
        )

    assert exc_info.value.status_code == 409


def test_job_cannot_pin_pair_outside_api_key_permissions(monkeypatch):
    monkeypatch.setattr(main, "_INTERNAL_SECRET", "internal-secret")
    _install_job_db(monkeypatch, _job())

    with pytest.raises(main.HTTPException) as exc_info:
        main._benchmark_provider_affinity(
            _headers(),
            {"model": "org/model"},
            [{"model_id": 1, "provider_id": 10, "type": "logosnode"}],
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_internal_benchmark_proxy_does_not_resolve_a_user_api_key(monkeypatch):
    monkeypatch.setattr(main, "DBManager", MagicMock(side_effect=AssertionError("user key must not be queried")))
    execute = AsyncMock(return_value="response")
    monkeypatch.setattr(main, "_execute_resource_mode", execute)
    auth = main.AuthContext(
        key_value="",
        api_key_id=-7,
        api_key_name="internal-model-benchmark",
        key_type="internal",
        team_id=None,
        user_id=None,
        environment="model-provider-benchmark",
        log_level="BILLING",
        settings={},
    )
    deployment = {"model_id": 1, "provider_id": 20, "type": "logosnode"}

    response = await main._execute_proxy_mode(
        body={"model": "org/model"},
        headers={},
        auth=auth,
        deployments=[deployment],
        log_id=None,
        is_async_job=False,
        required_provider_id=20,
    )

    assert response == "response"
    assert execute.await_args.kwargs["deployments"] == [deployment]
    assert execute.await_args.kwargs["allowed_models_override"] == [1]


@pytest.mark.asyncio
async def test_internal_benchmark_request_is_visible_in_request_logs(monkeypatch):
    logged = []

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_job(self, job_id):
            return {"request_payload": {"model_provider_id": 31}}

        def get_model_provider_benchmark_target(self, model_provider_id):
            return {
                "model_id": 1,
                "provider_id": 20,
                "provider_type": "logosnode",
                "model_name": "org/model",
            }

        def log_usage(self, **kwargs):
            logged.append(kwargs)
            return {"log-id": 99}, 200

    request = MagicMock()
    request.json = AsyncMock(return_value={"model": "org/model"})
    request.headers = {main.BENCHMARK_JOB_HEADER: "7"}
    planner = MagicMock()
    planner.prepare_benchmark_lane = AsyncMock(return_value=True)
    execute = AsyncMock(return_value="response")
    monkeypatch.setattr(main, "DBManager", DummyDB)
    monkeypatch.setattr(main, "_benchmark_provider_affinity", MagicMock(return_value=20))
    monkeypatch.setattr(main, "_capacity_planner", planner)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", AsyncMock(side_effect=lambda rows, payload: rows))
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", execute)

    response = await main.internal_model_benchmark_completion(7, "chat/completions", request)

    assert response == "response"
    assert logged == [
        {
            "api_key_id": None,
            "team_id": None,
            "user_id": None,
            "environment": "model-provider-benchmark",
            "log_level": "BILLING",
            "request_id": execute.await_args.kwargs["request_id"],
        }
    ]
    assert execute.await_args.kwargs["log_id"] == 99
    assert execute.await_args.kwargs["auth"].default_priority == 1


@pytest.mark.asyncio
async def test_sync_request_records_affinity_http_errors_on_the_request_log(monkeypatch):
    async def fake_auth_parse_log(request, use_profile_auth=False):
        auth = MagicMock(api_key_id=5)
        return {}, auth, {"model": "org/model"}, "127.0.0.1", 99

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def update_log_entry_metrics(self, **kwargs):
            pass

    failure = MagicMock()
    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "DBManager", DummyDB)
    monkeypatch.setattr(
        main,
        "request_setup",
        lambda headers, api_key_id, db=None: ([{"provider_id": 20, "model_id": 1}], ["org/model"]),
    )
    monkeypatch.setattr(
        main,
        "_benchmark_provider_affinity",
        MagicMock(side_effect=main.HTTPException(status_code=401, detail="Invalid benchmark worker affinity")),
    )
    monkeypatch.setattr(main, "_record_log_failure", failure)

    with pytest.raises(main.HTTPException) as exc_info:
        await main.handle_sync_request("chat/completions", MagicMock())

    assert exc_info.value.status_code == 401
    failure.assert_called_once()
    assert failure.call_args.args[0] == 99
    assert failure.call_args.args[2] == "Invalid benchmark worker affinity"
