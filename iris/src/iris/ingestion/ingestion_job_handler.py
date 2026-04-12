from threading import Semaphore, Thread

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units.
    Skips duplicate jobs if a thread is already running for the same lecture unit.
    """

    def __init__(self):
        self.job_list = {}
        self.semaphore = Semaphore(1)

    def add_job(
        self, process: Thread, course_id: int, lecture_id: int, lecture_unit_id: int
    ):
        self.semaphore.acquire()
        try:
            old_thread = None
            course_dict = self.job_list.get(course_id)
            if course_dict:
                lecture_dict = course_dict.get(lecture_id)
                if lecture_dict:
                    old_thread = lecture_dict.get(lecture_unit_id)

            if old_thread is not None and old_thread.is_alive():
                logger.info(
                    "Skipping duplicate ingestion job (already running) | "
                    "course=%d lecture=%d unit=%d",
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                )
                return

            self.job_list.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = process
            process.start()
        finally:
            self.semaphore.release()
