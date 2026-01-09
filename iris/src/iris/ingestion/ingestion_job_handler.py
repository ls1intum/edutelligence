from asyncio import Semaphore

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class IngestionJobHandler:
    """
    A handler to track the current ingestion jobs for lecture units,
    which kills a running process for a lecture unit if the same lecture unit is ingested again.
    """

    def __init__(self):
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
                "Terminated old ingestion process | course=%d lecture=%d unit=%d",
                course_id,
                lecture_id,
                lecture_unit_id,
            )
            self.job_list.setdefault(course_id, {}).setdefault(lecture_id, {})[
                lecture_unit_id
            ] = process
        process.start()
        self.semaphore.release()
