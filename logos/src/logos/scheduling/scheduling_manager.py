"""
Module handling all scheduling tasks in Logos.
"""
import functools
import logging
import time
from threading import Thread, Event
from scheduler import Scheduler, Task

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
        self.scheduler = scheduler
        self.thread = None
        self.return_value = None
        self.has_finished = False
        self.stop_event = Event()
        self.run()

    def add_request(self, data: dict, model_id: int, weight: int, priority: int):
        self.scheduler.enqueue(Task(data, model_id, weight, priority))

    def run(self):
        self.thread = Thread(target=self.__run)
        self.thread.start()

    def stop(self):
        """Signal the thread to stop and wait for it to finish."""
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # Wait for thread to exit gracefully
        logging.info("Scheduling Manager stopped.")

    def __run(self):
        """Main loop for processing requests."""
        while not self.stop_event.is_set():
            try:
                if not self.scheduler.is_empty() and not self.has_finished:
                    task = self.scheduler.schedule()
                    if task:
                        logging.info(f"Scheduling task: {task.data} for model {task.model_id}")
                        self.return_value = task
                        self.has_finished = True
                        logging.info(f"Task completed: {task.data}")
                    else:
                        time.sleep(0.1)
                else:
                    # No tasks in queue
                    time.sleep(0.1)
            except Exception as e:
                logging.error(f"Error in scheduling loop: {e}", exc_info=True)
                self.has_finished = False
                time.sleep(1)
