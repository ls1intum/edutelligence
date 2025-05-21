import threading
import time
import uuid
from collections import defaultdict
from typing import Any, Dict

# Job state store
JOB_RESULTS: Dict[str, Dict[str, Any]] = {}
JOB_LOCK = threading.Lock()


def create_job() -> str:
    """Create a new transcription job and return its ID."""
    job_id = str(uuid.uuid4())
    with JOB_LOCK:
        JOB_RESULTS[job_id] = {
            "status": "processing",
            "timestamp": time.time(),  # for cleanup purposes
        }
    return job_id


def save_job_result(job_id: str, result: Dict[str, Any]):
    """Mark job as complete and save the result."""
    with JOB_LOCK:
        JOB_RESULTS[job_id] = {"status": "done", "timestamp": time.time(), **result}


def fail_job(job_id: str, error: str):
    """Mark job as failed and store the error message."""
    with JOB_LOCK:
        JOB_RESULTS[job_id] = {
            "status": "error",
            "error": error,
            "timestamp": time.time(),
        }


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Return the status/result of the job."""
    with JOB_LOCK:
        return JOB_RESULTS.get(job_id, {"status": "not_found"})


def cleanup_finished_jobs(ttl_minutes: int = 60):
    """Remove jobs older than `ttl_minutes` (default: 60 minutes)."""
    now = time.time()
    with JOB_LOCK:
        expired = [
            job_id
            for job_id, data in JOB_RESULTS.items()
            if data.get("status") in {"done", "error"}
            and now - data.get("timestamp", now) > ttl_minutes * 60
        ]
        for job_id in expired:
            del JOB_RESULTS[job_id]
