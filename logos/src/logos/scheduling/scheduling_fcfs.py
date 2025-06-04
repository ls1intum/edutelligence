"""
Module implementing a basic FCFS-Scheduler for requests.
"""
from scheduler import Scheduler, Task


class FCFSScheduler(Scheduler):
    def __init__(self) -> None:
        super().__init__()

    def schedule(self) -> Task:
        return self.tasks.pop()
