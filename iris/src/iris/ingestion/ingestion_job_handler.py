import threading
from contextlib import contextmanager
from threading import Event, Thread
from typing import Iterator

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger
from iris.pipeline.lecture_update_lock import lecture_update_lock

logger = get_logger(__name__)

IngestionJobKey = tuple[str, int, int, int]


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    Starts every new job immediately and marks the previous same-unit job as
    superseded via its cancellation event.

    Production code shares the ``ingestion_job_handler`` singleton below; a
    fresh instance keeps its own registry, which is what tests want.
    """

    def __init__(self):
        self._jobs_lock = threading.Lock()
        self._running_jobs: dict[IngestionJobKey, Event] = {}
        self._superseded_jobs = 0

    @staticmethod
    def _job_key(
        base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
    ) -> IngestionJobKey:
        return (base_url, course_id, lecture_id, lecture_unit_id)

    def is_current_job(
        self,
        base_url: str,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ) -> bool:
        key = self._job_key(base_url, course_id, lecture_id, lecture_unit_id)
        with self._jobs_lock:
            return self._running_jobs.get(key) is cancel_event

    def create_cancellation_event(self) -> Event:
        return Event()

    @contextmanager
    def current_job_guard(
        self,
        base_url: str,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event | None,
        stage: str,
    ) -> Iterator[None]:
        if cancel_event is None:
            yield
            return
        with lecture_update_lock(base_url, course_id, lecture_id, lecture_unit_id):
            with self._jobs_lock:
                current_job = self._running_jobs.get(
                    self._job_key(base_url, course_id, lecture_id, lecture_unit_id)
                )
            if cancel_event.is_set() or (
                current_job is not None and current_job is not cancel_event
            ):
                raise IngestionCancelledException(
                    lecture_unit_id, f"Cancelled during {stage}"
                )
            yield

    def add_job(
        self,
        process: Thread,
        base_url: str,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ):
        key = self._job_key(base_url, course_id, lecture_id, lecture_unit_id)
        with lecture_update_lock(base_url, course_id, lecture_id, lecture_unit_id):
            with self._jobs_lock:
                previous_cancel_event = self._running_jobs.get(key)
                if previous_cancel_event is not None:
                    previous_cancel_event.set()
                    self._superseded_jobs += 1
                self._running_jobs[key] = cancel_event
                try:
                    process.start()
                except BaseException:
                    # No worker will ever call complete_job for this key, so drop it
                    # here — otherwise the unit stays registered as running forever.
                    if self._running_jobs.get(key) is cancel_event:
                        del self._running_jobs[key]
                    raise
                superseded_jobs = self._superseded_jobs
        if previous_cancel_event is not None:
            logger.info(
                "Started ingestion job, superseding the previous one | "
                "course=%d lecture=%d unit=%d total_superseded=%d",
                course_id,
                lecture_id,
                lecture_unit_id,
                superseded_jobs,
            )
        else:
            logger.info(
                "Started ingestion job | course=%d lecture=%d unit=%d",
                course_id,
                lecture_id,
                lecture_unit_id,
            )

    def complete_job(
        self,
        base_url: str,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ) -> None:
        key = self._job_key(base_url, course_id, lecture_id, lecture_unit_id)
        with self._jobs_lock:
            if self._running_jobs.get(key) is cancel_event:
                del self._running_jobs[key]


ingestion_job_handler = IngestionJobHandler()
"""Process-wide registry of running lecture ingestion jobs."""
