import asyncio
import time
import uuid
from typing import Any, Dict, Set

# Job state store
JOB_RESULTS: Dict[str, Dict[str, Any]] = {}
JOB_LOCK = asyncio.Lock()

# Track jobs that should be cancelled
CANCELLED_JOBS: Set[str] = set()
CANCELLED_JOBS_LOCK = asyncio.Lock()


async def create_job() -> str:
    """Create a new transcription job and return its ID."""
    job_id = str(uuid.uuid4())
    async with JOB_LOCK:
        JOB_RESULTS[job_id] = {
            "status": "processing",
            "timestamp": time.time(),  # for cleanup purposes
        }
    return job_id


async def save_job_result(job_id: str, result: Dict[str, Any]):
    """Mark job as complete and save the result."""
    async with JOB_LOCK:
        JOB_RESULTS[job_id] = {"status": "done", "timestamp": time.time(), **result}


async def fail_job(job_id: str, error: str):
    """Mark job as failed and store the error message."""
    async with JOB_LOCK:
        JOB_RESULTS[job_id] = {
            "status": "error",
            "error": error,
            "timestamp": time.time(),
        }


async def get_job_status(job_id: str) -> Dict[str, Any]:
    """Return the status/result of the job."""
    async with JOB_LOCK:
        return JOB_RESULTS.get(job_id, {"status": "not_found"})


async def cleanup_finished_jobs(ttl_minutes: int = 60):
    """Remove jobs older than `ttl_minutes` (default: 60 minutes)."""
    now = time.time()
    async with JOB_LOCK:
        expired = [
            job_id
            for job_id, data in JOB_RESULTS.items()
            if data.get("status") in {"done", "error"}
            and now - data.get("timestamp", now) > ttl_minutes * 60
        ]
        for job_id in expired:
            del JOB_RESULTS[job_id]


async def cancel_job(job_id: str):
    """Mark a job as cancelled."""
    async with CANCELLED_JOBS_LOCK:
        CANCELLED_JOBS.add(job_id)
    async with JOB_LOCK:
        if job_id in JOB_RESULTS:
            JOB_RESULTS[job_id] = {
                "status": "cancelled",
                "timestamp": time.time(),
            }


async def is_job_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled."""
    async with CANCELLED_JOBS_LOCK:
        return job_id in CANCELLED_JOBS


async def remove_from_cancelled(job_id: str):
    """Remove job from cancelled set (cleanup)."""
    async with CANCELLED_JOBS_LOCK:
        CANCELLED_JOBS.discard(job_id)
