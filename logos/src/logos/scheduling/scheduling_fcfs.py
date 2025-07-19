"""
Module implementing a basic FCFS-Scheduler for requests.
"""
from typing import Dict

from logos.scheduling.scheduler import Scheduler, Task


class FCFSScheduler(Scheduler):
    def __init__(self) -> None:
        super().__init__()

    def schedule(self, work_table: Dict[int, bool]) -> Task | None:
        for key in self.tasks:
            available = work_table.get(key, 0)
            if self.tasks[key] and available > 0:
                return self.tasks[key].popleft()
        return None
