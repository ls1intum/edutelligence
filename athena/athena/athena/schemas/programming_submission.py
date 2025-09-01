from pydantic import Field
from git.repo import Repo

from athena.helpers.programming.code_repository import get_repository
from athena.schemas.submission import Submission


class ProgrammingSubmission(Submission):
    """Submission on a programming exercise."""
    repository_uri: str = Field(example="https://lms.example.com/assignments/1/submissions/1/download")


    def get_repository(self) -> Repo:
        """Return the submission repository as a Repo object."""
        return get_repository(self.repository_uri)
    
    def get_code(self, file_path: str) -> str:
        """
        Fetches the code from the submission repository.
        Might be quite an expensive operation! If you need to fetch multiple files, consider using get_repository() instead.
        """
        repo = self.get_repository()
        file_on_disk = (repo.working_tree_dir or ".") + "/" + file_path
        with open(file_on_disk, "r", encoding="utf-8") as f:
            return f.read()
