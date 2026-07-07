from threading import Event, Semaphore, Thread

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    For duplicate jobs (same course/lecture/unit), the most recent request wins.
    """

    def __init__(self):
        self.job_list = {}
        self.cancel_events = {}  # Track cancellation events
        self.semaphore = Semaphore(1)

    def create_cancellation_event(self) -> Event:
        """Create a new cancellation event for a job."""
        return Event()

    def add_job(
        self,
        process: Thread,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ):
        """Add a new ingestion job, cancelling any existing job for same lecture unit."""
        self.semaphore.acquire()
        try:
            # Find old job and its cancel event
            old_thread = None
            old_cancel_event = None

            course_dict = self.job_list.get(course_id)
            if course_dict:
                lecture_dict = course_dict.get(lecture_id)
                if lecture_dict:
                    old_thread = lecture_dict.get(lecture_unit_id)

            cancel_dict = self.cancel_events.get(course_id)
            if cancel_dict:
                cancel_lecture_dict = cancel_dict.get(lecture_id)
                if cancel_lecture_dict:
                    old_cancel_event = cancel_lecture_dict.get(lecture_unit_id)

            # Signal old job to cancel
            if old_thread is not None and old_thread.is_alive():
                logger.info(
                    "Cancelling existing ingestion job (superseded by new request) | "
                    "course=%d lecture=%d unit=%d",
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                )
                if old_cancel_event is not None:
                    old_cancel_event.set()  # Signal cancellation

            # Register new job
            self.job_list.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = process
            self.cancel_events.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = cancel_event

            process.start()

            logger.info(
                "Started new ingestion job | course=%d lecture=%d unit=%d",
                course_id,
                lecture_id,
                lecture_unit_id,
            )
        finally:
            self.semaphore.release()
