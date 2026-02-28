from threading import Semaphore

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class JobHandler:
    """
    A handler to track running jobs for lecture units,
    which kills a running process for a lecture unit if the same lecture unit is submitted again.
    """

    def __init__(self, job_type: str = "job"):
        self.job_type = job_type
        self.job_list = {}
        self.semaphore = Semaphore(1)

    def add_job(self, process, course_id: int, lecture_id: int, lecture_unit_id: int):
        self.semaphore.acquire()
        old_process = None
        course_dict = self.job_list.get(course_id)
        if course_dict:
            lecture_dict = course_dict.get(lecture_id)
            if lecture_dict:
                old_process = lecture_dict.get(lecture_unit_id)
        if old_process is None:
            self.job_list.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = process
        else:
            old_process.terminate()
            old_process.join()
            logger.debug(
                "Terminated old %s process | course=%d lecture=%d unit=%d",
                self.job_type,
                course_id,
                lecture_id,
                lecture_unit_id,
            )
            self.job_list.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = process
        process.start()
        self.semaphore.release()

    def cancel_job(self, course_id: int, lecture_id: int, lecture_unit_id: int):
        self.semaphore.acquire()
        try:
            process = (
                self.job_list.get(course_id, {})
                .get(lecture_id, {})
                .get(lecture_unit_id)
            )
            if process is not None:
                process.terminate()
                process.join()
                del self.job_list[course_id][lecture_id][lecture_unit_id]
                logger.info(
                    "Cancelled %s job | course=%d lecture=%d unit=%d",
                    self.job_type,
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                )
            else:
                logger.debug(
                    "No active %s job to cancel | course=%d lecture=%d unit=%d",
                    self.job_type,
                    course_id,
                    lecture_id,
                    lecture_unit_id,
                )
        finally:
            self.semaphore.release()
