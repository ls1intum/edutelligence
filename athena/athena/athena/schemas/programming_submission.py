from pydantic import Field
from git.repo import Repo
from pathlib import Path
from athena.helpers.programming.path_utils import ensure_safe_path

from athena.helpers.programming.code_repository import get_repository
from athena.schemas.submission import Submission


class ProgrammingSubmission(Submission):
    """Submission on a programming exercise."""
    repository_uri: str = Field(examples=["https://lms.example.com/assignments/1/submissions/1/download"])


    def get_repository(self) -> Repo:
        """Return the submission repository as a Repo object."""
        return get_repository(self.repository_uri)
    
    def get_code(self, file_path: str) -> str:
        """
        Fetches the code from the submission repository.
        Might be quite an expensive operation! If you need to fetch multiple files, consider using get_repository() instead.
        """
        repo = self.get_repository()
        root = Path(repo.working_tree_dir or ".").resolve()
        target = ensure_safe_path(root, file_path, ignore_git=True)
        if not target.is_file():
            raise FileNotFoundError(f"File not found in repository: {file_path}")
        return target.read_text(encoding="utf-8")
