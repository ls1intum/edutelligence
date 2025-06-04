import time

from nebula.transcript import jobs


def test_create_and_save_job():
    job_id = jobs.create_job()
    assert job_id in jobs.JOB_RESULTS
    assert jobs.JOB_RESULTS[job_id]["status"] == "processing"

    jobs.save_job_result(
        job_id,
        {
            "lectureUnitId": 123,
            "language": "en",
            "segments": [
                {"startTime": 0, "endTime": 1, "text": "hello", "slideNumber": 1}
            ],
        },
    )

    result = jobs.get_job_status(job_id)
    assert result["status"] == "done"
    assert result["lectureUnitId"] == 123


def test_fail_job():
    job_id = jobs.create_job()
    jobs.fail_job(job_id, "transcription failed")
    result = jobs.get_job_status(job_id)
    assert result["status"] == "error"
    assert result["error"] == "transcription failed"


def test_get_nonexistent_job():
    result = jobs.get_job_status("nonexistent-id")
    assert result["status"] == "not_found"


def test_cleanup_finished_jobs():
    job_id = jobs.create_job()
    jobs.save_job_result(
        job_id,
        {
            "lectureUnitId": 42,
            "language": "en",
            "segments": [],
        },
    )

    # Simulate an old job (e.g., 2 hours old)
    jobs.JOB_RESULTS[job_id]["timestamp"] = time.time() - (2 * 60 * 60)

    jobs.cleanup_finished_jobs(ttl_minutes=60)

    assert jobs.get_job_status(job_id)["status"] == "not_found"
