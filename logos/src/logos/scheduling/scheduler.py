"""
Base scheduler for requests.
"""
from collections import deque, defaultdict
from typing import Dict, List, Tuple


class Task:
    def __init__(self, data: dict, models: List[Tuple[int, float, int, int]], task_id: int) -> None:
        self.data = data
        self.models = models
        self.__id = task_id

    def get_id(self):
        return self.__id

    def get_best_model_id(self):
        if len(self.models) == 0:
            return None
        return self.models[0][0]


class Scheduler:
    def __init__(self) -> None:
        self.tasks = defaultdict(deque)

    def enqueue(self, task: Task):
        self.tasks[task.models[0][0]].append(task)

    def schedule(self, work_table: Dict[int, int]) -> Task | None:
        raise NotImplementedError("Schedule must be overridden by classifiers")
    
    def is_empty(self):
        return all(len(q) == 0 for q in self.tasks.values())

    def get_depth_for_model(self, model_id: int) -> int:
        """
        Return current queued depth for a model. Subclasses with custom queue
        implementations should override this for accurate metrics.
        """
        queue = self.tasks.get(model_id)
        return len(queue) if queue else 0
