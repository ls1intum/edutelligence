from typing import Optional, List

from git import Repo

from athena import GradingCriterion
from module_programming_llm.prompts.generate_suggestions_by_file import GenerateSuggestionsByFileOutput
from module_programming_llm.prompts.split_grading_instructions_by_file import SplitGradingInstructionsByFileOutput
from module_programming_llm.prompts.split_problem_statement_by_file import SplitProblemStatementByFileOutput


class ValidateSuggestionsInput:
    """
    DTO class for filtering out
    """
    solution_repo: Repo
    template_repo: Repo
    submission_repo: Repo
    problem_statement_by_file: Optional[SplitProblemStatementByFileOutput]
    problem_statement: Optional[str]
    exercise_id: int
    submission_id: int
    feedback_suggestions: List[Optional[GenerateSuggestionsByFileOutput]]
    grading_instructions_by_file: Optional[SplitGradingInstructionsByFileOutput]
    grading_criteria: Optional[List[GradingCriterion]]
    grading_instructions: Optional[str]
    solution_summary: str
    max_points: float
    bonus_points: float
    programming_language: str

    def __init__(
            self,
            solution_repo: Repo,
            template_repo: Repo,
            submission_repo: Repo,
            problem_statement_by_file: Optional[SplitProblemStatementByFileOutput],
            problem_statement: Optional[str],
            exercise_id: int,
            submission_id: int,
            feedback_suggestions: List[Optional[GenerateSuggestionsByFileOutput]],
            grading_instructions_by_file: Optional[SplitGradingInstructionsByFileOutput],
            grading_criteria: Optional[List[GradingCriterion]],
            grading_instructions: Optional[str],
            solution_summary: str,
            max_points: float,
            bonus_points: float,
            programming_language: str
    ):
        self.solution_repo = solution_repo
        self.template_repo = template_repo
        self.submission_repo = submission_repo
        self.problem_statement_by_file = problem_statement_by_file
        self.problem_statement = problem_statement
        self.exercise_id = exercise_id
        self.submission_id = submission_id
        self.feedback_suggestions = feedback_suggestions
        self.grading_instructions_by_file = grading_instructions_by_file
        self.grading_criteria = grading_criteria
        self.grading_instructions = grading_instructions
        self.solution_summary = solution_summary
        self.max_points = max_points
        self.bonus_points = bonus_points
        self.programming_language = programming_language
