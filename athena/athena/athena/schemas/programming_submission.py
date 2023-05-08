from pydantic import Field

from . import Submission


class ProgrammingSubmission(Submission):
    """Submission on a programming exercise."""
    repository_url: str = Field(example="https://lms.example.com/assignments/1/submissions/1/download")
