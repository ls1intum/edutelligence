from typing import List

from pydantic import BaseModel


class BuildLogEntry(BaseModel):
    time: str
    message: str

    def __str__(self):
        return f'BuildLogEntry(time="{self.time}", message="{self.message}")'


class ProgrammingSubmission(BaseModel):
    commit_hash: str
    build_failed: bool
    build_log_entries: List[BuildLogEntry]

    def __str__(self):
        return (
            f'ProgrammingSubmission(commit_hash="{self.commit_hash}", build_failed={self.build_failed}, '
            f"build_log_entries={self.build_log_entries})"
        )
