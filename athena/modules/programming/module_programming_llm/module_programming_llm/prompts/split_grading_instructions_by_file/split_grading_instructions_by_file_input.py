from typing import Optional, List

from git import Repo

from athena import GradingCriterion


class SplitGradingInstructionsByFileInput:
    """
    A DTO file that contains information about grading instructions and submission
    """
    grading_instructions: Optional[str]
    grading_criteria: Optional[List[GradingCriterion]]
    template_repo: Repo
    submission_repo: Repo
    solution_repo: Repo
    exercise_id: int
    submission_id: int

    def __init__(self, template_repo: Repo, submission_repo: Repo, solution_repo: Repo, exercise_id: int = 1,
                 submission_id: int = 1, grading_instructions: Optional[str] = None,
                 grading_criteria: Optional[List[GradingCriterion]] = None):
        self.grading_instructions = grading_instructions
        self.grading_criteria = grading_criteria
        self.template_repo = template_repo
        self.submission_repo = submission_repo
        self.solution_repo = solution_repo
        self.exercise_id = exercise_id
        self.submission_id = submission_id