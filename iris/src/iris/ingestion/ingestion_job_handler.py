import threading
from threading import Event, Thread

from iris.common.logging_config import get_logger
from iris.ingestion.ingestion_job_registry import (
    clear_current_job_cancel_event,
    current_job_cancel_event,
    ingestion_job_commit_lock,
    set_current_job_cancel_event,
)

logger = get_logger(__name__)


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    Starts every new job immediately and marks the previous same-unit job as
    superseded via its cancellation event.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._superseded_jobs = 0

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
        with ingestion_job_commit_lock(
            base_url, course_id, lecture_id, lecture_unit_id
        ):
            with self._lock:
                previous_cancel_event = current_job_cancel_event(
                    base_url, course_id, lecture_id, lecture_unit_id
                )
                if previous_cancel_event is not None:
                    previous_cancel_event.set()
                    self._superseded_jobs += 1
                set_current_job_cancel_event(
                    base_url,
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                    cancel_event,
                )
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
        with ingestion_job_commit_lock(
            base_url, course_id, lecture_id, lecture_unit_id
        ):
            clear_current_job_cancel_event(
                base_url,
                course_id,
                lecture_id,
                lecture_unit_id,
                cancel_event,
            )
