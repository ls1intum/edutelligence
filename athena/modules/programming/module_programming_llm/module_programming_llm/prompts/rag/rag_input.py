from typing import Optional

from git import Repo


class RAGInput:
    """
    DTO class for top level feedback generation job
    """
    template_repo: Repo
    solution_repo: Repo
    exercise_id: int
    problem_statement: Optional[str]

    def __init__(self,
                 template_repo: Repo,
                 solution_repo: Repo,
                 exercise_id: int,
                 problem_statement: Optional[str] = None):
        self.template_repo = template_repo
        self.solution_repo = solution_repo
        self.exercise_id = exercise_id
        self.problem_statement = problem_statement
