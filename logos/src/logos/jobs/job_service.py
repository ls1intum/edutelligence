"""
Minimal helpers for persisting async job state.
"""
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import JobStatus


@dataclass
class JobSubmission:
    """
    Payload describing a job to run asynchronously.
    """
    path: str
    method: str
    headers: Dict[str, str]
    body: Dict[str, Any]
    client_ip: str


class JobService:
    """
    Persistence helper for async jobs: create, update status, and fetch job records.
    """
    @staticmethod
    def create_job(submission: JobSubmission) -> int:
        """
        Store a new job and return its id.
        """
        payload: Dict[str, Any] = asdict(submission)
        with DBManager() as db:
            return db.create_job_record(payload, JobStatus.PENDING.value)

    @staticmethod
    def mark_running(job_id: int) -> None:
        """
        Mark the job as running.
        """
        with DBManager() as db:
            db.update_job_status(job_id, JobStatus.RUNNING.value)

    @staticmethod
    def mark_success(job_id: int, result_payload: Dict[str, Any]) -> None:
        """
        Mark the job as succeeded and store its result payload.
        """
        with DBManager() as db:
            db.update_job_status(job_id, JobStatus.SUCCESS.value, result_payload=result_payload, error_message=None)

    @staticmethod
    def mark_failed(job_id: int, error_message: str) -> None:
        """
        Mark the job as failed and persist the error message.
        """
        logging.error("Job %s failed: %s", job_id, error_message)
        with DBManager() as db:
            db.update_job_status(job_id, JobStatus.FAILED.value, error_message=error_message)

    @staticmethod
    def fetch(job_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch the persisted state of a job by id.
        """
        with DBManager() as db:
            return db.get_job(job_id)
