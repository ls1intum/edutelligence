from typing import Optional, List

from git import Repo

from athena import GradingCriterion
from module_programming_llm.prompts.split_grading_instructions_by_file import SplitGradingInstructionsByFileOutput
from module_programming_llm.prompts.split_problem_statement_by_file import SplitProblemStatementByFileOutput


class GenerateSuggestionsByFileInput:
    """
    DTO class for top level feedback generation job
    """
    template_repo: Repo
    submission_repo: Repo
    solution_repo: Repo
    exercise_id: int
    submission_id: int
    grading_instructions_by_file: SplitGradingInstructionsByFileOutput
    grading_criteria: Optional[List[GradingCriterion]]
    problem_statement_by_file: SplitProblemStatementByFileOutput
    problem_statement: Optional[str]
    grading_instructions: Optional[str]
    max_points: float
    bonus_points: float
    programming_language: str

    def __init__(self,
                 template_repo: Repo,
                 submission_repo: Repo,
                 solution_repo: Repo,
                 exercise_id: int,
                 submission_id: int,
                 max_points: float,
                 bonus_points: float,
                 programming_language: str,
                 grading_instructions_by_file: Optional[SplitGradingInstructionsByFileOutput] = None,
                 problem_statement_by_file: Optional[SplitProblemStatementByFileOutput] = None,
                 grading_criteria: Optional[List[GradingCriterion]] = None,
                 problem_statement: Optional[str] = None,
                 grading_instructions: Optional[str] = None):
        self.template_repo = template_repo
        self.submission_repo = submission_repo
        self.solution_repo = solution_repo
        self.exercise_id = exercise_id
        self.submission_id = submission_id
        self.grading_instructions_by_file = grading_instructions_by_file
        self.grading_criteria = grading_criteria
        self.problem_statement_by_file = problem_statement_by_file
        self.problem_statement = problem_statement
        self.grading_instructions = grading_instructions
        self.max_points = max_points
        self.bonus_points = bonus_points
        self.programming_language = programming_language
