from pydantic import Field
from zipfile import ZipFile
from git import Repo

from athena.helpers.programming.code_repository import get_repository_zip, get_repository
from .submission import Submission


class ProgrammingSubmission(Submission):
    """Submission on a programming exercise."""
    repository_url: str = Field(example="https://lms.example.com/assignments/1/submissions/1/download")


    def get_zip(self) -> ZipFile:
        """Return the submission repository as a ZipFile object."""
        return get_repository_zip(self.repository_url)


    def get_repository(self) -> Repo:
        """Return the submission repository as a Repo object."""
        return get_repository(self.repository_url)