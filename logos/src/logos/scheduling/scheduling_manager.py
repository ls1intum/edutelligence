"""
Module handling all scheduling tasks in Logos.
"""
import functools
import logging
import time
from threading import Thread, Event
from typing import Union, List, Tuple, Optional

from logos.scheduling.scheduler import Scheduler, Task
from logos.monitoring.recorder import MonitoringRecorder


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
    def __init__(self, scheduler: Scheduler, monitoring_recorder: Optional[MonitoringRecorder] = None):
        self.__scheduler = scheduler
        self.__thread = None
        self.__return_value = None
        self.__has_finished = False
        self.__running = False
        self.__stop_event = Event()
        self.__ticket = 0
        self.__finished_ticket = -1
        self.__is_free = dict()
        self.__monitoring = monitoring_recorder or MonitoringRecorder()

    def add_request(self, data: dict, models: List[Tuple[int, float, int, int]]):
        for (mid, _, _, par) in models:
            if mid not in self.__is_free:
                self.__is_free[mid] = par
        task = Task(data, models, self.__ticket)
        self.__scheduler.enqueue(task)

        if self.__monitoring and models:
            model_id, _, priority_int, _ = models[0]
            queue_depth = self.__scheduler.get_depth_for_model(model_id)
            timeout_s = data.get("timeout_s") if isinstance(data, dict) else None
            # TODO: if model reassignment between queues is added, capture the reassignment timestamp and depth.
            # provider_id is unknown here because model→provider resolution happens after scheduling.
            self.__monitoring.record_enqueue(
                request_id=str(task.get_id()),
                model_id=model_id,
                provider_id=None,
                initial_priority=str(priority_int),
                queue_depth=queue_depth,
                timeout_s=timeout_s,
            )

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

                        if self.__monitoring and mid is not None:
                            depth_after_dequeue = self.__scheduler.get_depth_for_model(mid)
                            queue_depth_at_schedule = depth_after_dequeue + 1  # account for the dequeued task
                            priority_int = task.models[0][2] if task.models else None
                            self.__monitoring.record_scheduled(
                                request_id=str(task.get_id()),
                                model_id=mid,
                                priority_when_scheduled=str(priority_int) if priority_int is not None else None,
                                queue_depth_at_schedule=queue_depth_at_schedule,
                            )

                        logging.info(f"Task {task.get_id()} scheduled for model {mid}")
                else:
                    # No tasks in queue
                    time.sleep(0.1)
            except Exception as e:
                logging.error(f"Error in scheduling loop: {e}")
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

    def get_monitoring(self) -> MonitoringRecorder:
        """Expose the monitoring recorder used by this manager."""
        return self.__monitoring
