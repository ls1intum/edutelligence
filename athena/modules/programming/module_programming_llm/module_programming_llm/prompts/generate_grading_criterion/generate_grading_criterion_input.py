from typing import Optional

from git import Repo


class GenerateGradingCriterionInput:
    """
    DTO class for top level feedback generation job
    """
    template_repo: Repo
    solution_repo: Repo
    exercise_id: int
    problem_statement: Optional[str]
    grading_instructions: Optional[str]
    max_points: float
    bonus_points: float

    def __init__(self,
                 template_repo: Repo,
                 solution_repo: Repo,
                 exercise_id: int,
                 max_points: float,
                 bonus_points: float,
                 problem_statement: Optional[str] = None,
                 grading_instructions: Optional[str] = None):
        self.template_repo = template_repo
        self.solution_repo = solution_repo
        self.exercise_id = exercise_id
        self.problem_statement = problem_statement
        self.grading_instructions = grading_instructions
        self.max_points = max_points
        self.bonus_points = bonus_points
