"""
Module handling all scheduling tasks in Logos.
"""
import functools
import logging
import time
from threading import Thread, Event
from typing import Union, List, Tuple
from logos.classification.classification_manager import ClassificationManager
from logos.classification.classify_policy import PolicyClassifier
import data
from logos.classification.proxy_policy import ProxyPolicy
from scheduler import Scheduler, Task
from scheduling_fcfs import FCFSScheduler

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

    def add_request(self, data: dict, models: List[Tuple[int, float, int]]):
        for (mid, wgt, pri) in models:
            if mid not in self.__is_free:
                self.__is_free[mid] = True
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
                        mid = task.models[0][0]
                        logging.info(f"Scheduling task: {task.get_id()} for model {mid}")
                        self.__return_value = task
                        self.__has_finished = True
                        self.__finished_ticket = task.get_id()
                        self.__is_free[mid] = False
                        logging.info(f"Task completed: {task.get_id()}")
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
        self.__is_free[model_id] = True

    def is_finished(self, tid: int) -> bool:
        return self.__has_finished and self.__finished_ticket == tid


if __name__ == "__main__":
    select = ClassificationManager(data.models)
    tasks = select.classify("absolutely no idea", ProxyPolicy())
    tasks = [(2, 387.0, 0), (3, 371.0, 0), (1, 365.0, 0), (2, 365.0, 0), (1, 360.0, 0), (2, 350.0, 0)]
    print(tasks)
    def exec_task(data, model_id, weight, priority):
        sm = SchedulingManager(FCFSScheduler())
        sm.run()
        tid = sm.add_request(data, tasks)
        while not sm.is_finished(tid):
            pass

        out = sm.get_result()
        # -- DO SOMETHING --
        if model_id == 2:
            time.sleep(1)
        if model_id == 1:
            time.sleep(0.5)
        if out is not None:
            print(out.data)
        sm.set_free(model_id)

    ts = list()
    for (model_id, weight, priority), text in zip(tasks, ["a", "b", "c", "d", "e", "f"]):
        t = Thread(target=exec_task, args=(text, model_id, weight, priority))
        t.start()
        ts.append(t)
    start = time.time()
    while ts:
        ts = [i for i in ts if i.is_alive()]
    print("{:.2f}".format(time.time() - start))

    sm = SchedulingManager(FCFSScheduler())
    sm.stop()
