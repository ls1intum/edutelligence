from typing import Optional

from git import Repo
from pydantic import Field


class SplitProblemStatementByFileInput:
    """
    A DTO file that contains information about a programming exercise
    """
    problem_statement: Optional[str]
    template_repo: Repo
    submission_repo: Repo
    solution_repo: Repo
    exercise_id: int
    submission_id: int


    def __init__(self, template_repo: Repo, submission_repo: Repo, solution_repo: Repo,
                 problem_statement: Optional[str] = None, exercise_id: int = 1, submission_id: int = 1):
        self.problem_statement = problem_statement
        self.template_repo = template_repo
        self.submission_repo = submission_repo
        self.solution_repo = solution_repo
        self.exercise_id = exercise_id
        self.submission_id = submission_id
