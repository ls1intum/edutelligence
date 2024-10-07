from typing import Optional, List

from git import Repo

from module_programming_llm.prompts import GenerateSuggestionsByFileOutput
from module_programming_llm.prompts.split_problem_statement_by_file import SplitProblemStatementByFileOutput


class FilterOutSolutionInput:
    """
    DTO class for filtering out
    """
    solution_repo: Repo
    template_repo: Repo
    problem_statement_by_file: Optional[SplitProblemStatementByFileOutput]
    problem_statement: Optional[str]
    exercise_id: int
    submission_id: int
    feedback_suggestions: List[Optional[GenerateSuggestionsByFileOutput]]

    def __init__(self, solution_repo: Repo, template_repo: Repo, problem_statement: Optional[str], exercise_id: int,
                 submission_id: int, feedback_suggestions: List[Optional[GenerateSuggestionsByFileOutput]],
                 problem_statement_by_file: Optional[SplitProblemStatementByFileOutput]):
        self.solution_repo = solution_repo
        self.template_repo = template_repo
        self.exercise_id = exercise_id
        self.submission_id = submission_id
        if problem_statement_by_file is not None:
            self.problem_statement_by_file = problem_statement_by_file
        self.problem_statement = problem_statement
        self.feedback_suggestions = feedback_suggestions
