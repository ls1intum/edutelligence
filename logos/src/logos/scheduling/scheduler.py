"""
Base scheduler for requests.
"""
from collections import deque, defaultdict
from typing import Dict


class Task:
    def __init__(self, data: dict, model_id: int, weight: int, priority: int, task_id: int) -> None:
        self.data = data
        self.model_id = model_id
        self.weight = weight
        self.priority = priority
        self.__id = task_id

    def get_id(self):
        return self.__id


class Scheduler:
    def __init__(self) -> None:
        self.tasks = defaultdict(deque)

    def enqueue(self, task: Task):
        self.tasks[task.model_id].append(task)

    def schedule(self, work_table: Dict[int, bool]) -> Task | None:
        raise NotImplementedError("Schedule must be overridden by classifiers")
    
    def is_empty(self):
        return len(self.tasks) == 0
