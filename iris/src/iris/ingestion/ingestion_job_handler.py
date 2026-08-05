import threading
from threading import Event, Thread

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    Skips duplicate jobs if a thread is already running for the same lecture unit.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._latest = {}
        self._superseded_jobs = 0

    def create_cancellation_event(self) -> Event:
        return Event()

    def add_job(
        self,
        process: Thread,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ):
        key = (course_id, lecture_id, lecture_unit_id)
        with self._lock:
            previous_cancel_event = self._latest.get(key)
            if previous_cancel_event is not None:
                previous_cancel_event.set()
                self._superseded_jobs += 1
            self._latest[key] = cancel_event
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
