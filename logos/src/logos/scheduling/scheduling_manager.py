"""
Module handling all scheduling tasks in Logos.
"""
import functools
import logging
import time
from threading import Thread, Event
from typing import Union, List, Tuple

from logos.scheduling.scheduler import Scheduler, Task

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def singleton(cls):
    """
    A decorator to make a class a Singleton.
    """
    instances = {}

    @functools.wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class SchedulingManager:
    def __init__(self, scheduler: Scheduler):
        self.__scheduler = scheduler
        self.__thread = None
        self.__return_value = None
        self.__has_finished = False
        self.__running = False
        self.__stop_event = Event()
        self.__ticket = 0
        self.__finished_ticket = -1
        self.__is_free = dict()

    def add_request(self, data: dict, models: List[Tuple[int, float, int, int]]):
        for (mid, _, _, par) in models:
            if mid not in self.__is_free:
                self.__is_free[mid] = par
        self.__scheduler.enqueue(Task(data, models, self.__ticket))
        self.__ticket += 1
        return self.__ticket - 1

    def run(self):
        if self.__running:
            return
        self.__thread = Thread(target=self.__run)
        self.__thread.start()
        self.__running = True

    def stop(self):
        """Signal the thread to stop and wait for it to finish."""
        self.__stop_event.set()
        if self.__thread:
            self.__thread.join()  # Wait for thread to exit gracefully
        self.__running = False
        logging.info("Scheduling Manager stopped.")

    def __run(self):
        """
        Main loop for processing requests.
        """
        while not self.__stop_event.is_set():
            try:
                if not self.__scheduler.is_empty() and not self.__has_finished:
                    task = self.__scheduler.schedule(self.__is_free)
                    if task is not None:
                        mid = task.get_best_model_id()
                        self.__return_value = task
                        self.__has_finished = True
                        self.__finished_ticket = task.get_id()
                        self.__is_free[mid] -= 1
                        # logging.info(f"Task {task.get_id()} scheduled for model {mid}")
                        print(f"Task {task.get_id()} scheduled for model {mid}", flush=True)
                else:
                    # No tasks in queue
                    time.sleep(0.1)
            except Exception as e:
                logging.error(f"Error in scheduling loop: {e}", exc_info=True)
                self.__has_finished = False
                time.sleep(1)

    def get_result(self) -> Union[Task, None]:
        try:
            if not self.__has_finished:
                return None
            return self.__return_value
        finally:
            self.__has_finished = False
            self.__finished_ticket = -1

    def set_free(self, model_id: int):
        self.__is_free[model_id] += 1

    def is_finished(self, tid: int) -> bool:
        return self.__has_finished and self.__finished_ticket == tid
