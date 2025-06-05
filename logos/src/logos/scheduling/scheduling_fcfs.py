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
            if self.tasks[key] and work_table[key]:
                return self.tasks[key].pop()
        return None
