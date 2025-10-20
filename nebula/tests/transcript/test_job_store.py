# tests/transcript/test_job_store.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel
import pytest

from nebula.transcript.jobs import (
    cleanup_finished_jobs,
    create_job,
    fail_job,
    get_job_status,
    save_job_result,
)


@pytest.mark.anyio
async def test_create_and_get_status():
    job_id = await create_job()
    status = await get_job_status(job_id)
    assert status["status"] == "processing"


@pytest.mark.anyio
async def test_save_job_result_marks_done():
    job_id = await create_job()
    await save_job_result(
        job_id, {"result": {"segments": [{"start": 0.0, "end": 1.0, "text": "Hi"}]}}
    )
    status = await get_job_status(job_id)
    assert status["status"] == "done"
    assert status["result"]["segments"][0]["text"] == "Hi"


@pytest.mark.anyio
async def test_fail_job_marks_error():
    job_id = await create_job()
    await fail_job(job_id, "bad things")
    status = await get_job_status(job_id)
    assert status["status"] == "error"
    assert status["error"] == "bad things"


@pytest.mark.anyio
async def test_cleanup_finished_jobs_removes_old_entries(monkeypatch):
    job_id1 = await create_job()
    await fail_job(job_id1, "x")
    job_id2 = await create_job()
    await save_job_result(job_id2, {"result": {}})

    # Backdate timestamps to simulate age
    from nebula.transcript.jobs import JOB_RESULTS

    JOB_RESULTS[job_id1]["timestamp"] -= 61 * 60
    JOB_RESULTS[job_id2]["timestamp"] -= 61 * 60

    await cleanup_finished_jobs(ttl_minutes=60)

    assert (await get_job_status(job_id1))["status"] == "not_found"
    assert (await get_job_status(job_id2))["status"] == "not_found"
