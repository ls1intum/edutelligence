from unittest.mock import MagicMock

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
