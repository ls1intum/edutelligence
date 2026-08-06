import threading
from threading import Event, Thread

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

IngestionJobKey = tuple[str, int, int, int]


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    Starts every new job immediately and marks the previous same-unit job as
    superseded via its cancellation event.
    """

    _jobs_lock = threading.Lock()
    _running_jobs: dict[IngestionJobKey, Event] = {}

    def __init__(self):
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
        with self._jobs_lock:
            previous_cancel_event = self._running_jobs.get(key)
            if previous_cancel_event is not None:
                previous_cancel_event.set()
                self._superseded_jobs += 1
            self._running_jobs[key] = cancel_event
            process.start()
        if previous_cancel_event is not None:
            logger.info(
                "Superseding running ingestion job | course=%d lecture=%d unit=%d total_superseded=%d",
                course_id,
                lecture_id,
                lecture_unit_id,
                self._superseded_jobs,
            )
        logger.info(
            "Started ingestion job%s | course=%d lecture=%d unit=%d",
            ", superseding the previous one" if previous_cancel_event else "",
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
