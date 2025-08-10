# tests/transcript/test_job_store.py
import time

from nebula.transcript.jobs import (
    cleanup_finished_jobs,
    create_job,
    fail_job,
    get_job_status,
    save_job_result,
)


def test_create_and_get_status():
    job_id = create_job()
    status = get_job_status(job_id)
    assert status["status"] == "processing"


def test_save_job_result_marks_done():
    job_id = create_job()
    save_job_result(
        job_id, {"result": {"segments": [{"start": 0.0, "end": 1.0, "text": "Hi"}]}}
    )
    status = get_job_status(job_id)
    assert status["status"] == "done"
    assert status["result"]["segments"][0]["text"] == "Hi"


def test_fail_job_marks_error():
    job_id = create_job()
    fail_job(job_id, "bad things")
    status = get_job_status(job_id)
    assert status["status"] == "error"
    assert status["error"] == "bad things"


def test_cleanup_finished_jobs_removes_old_entries(monkeypatch):
    job_id1 = create_job()
    fail_job(job_id1, "x")
    job_id2 = create_job()
    save_job_result(job_id2, {"result": {}})

    # Backdate timestamps to simulate age
    from nebula.transcript.jobs import JOB_RESULTS

    JOB_RESULTS[job_id1]["timestamp"] -= 61 * 60
    JOB_RESULTS[job_id2]["timestamp"] -= 61 * 60

    cleanup_finished_jobs(ttl_minutes=60)

    assert get_job_status(job_id1)["status"] == "not_found"
    assert get_job_status(job_id2)["status"] == "not_found"
