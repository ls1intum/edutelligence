"""
Base scheduler for requests.
"""
from typing import List
from collections import deque


class Task:
    def __init__(self, data: dict, model_id: int, weight: int, priority: int) -> None:
        self.data = data
        self.model_id = model_id
        self.weight = weight
        self.priority = priority


class Scheduler:
    def __init__(self) -> None:
        self.tasks = deque()

    def enqueue(self, task: Task):
        self.tasks.append(task)

    def schedule(self) -> Task:
        raise NotImplementedError("Schedule must be overriden by classifiers")
    
    def is_empty(self):
        return len(self.tasks) == 0
