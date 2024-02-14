from domain import (
    Course,
    ProgrammingExercise,
    IrisMessage,
    ProgrammingSubmission,
    CodeHint,
)


class ProgrammingExerciseTutorChatDTO:
    def __init__(
        self,
        course: Course,
        exercise: ProgrammingExercise,
        submission: ProgrammingSubmission,
        chat_history: [IrisMessage],
    ):
        self.course = course
        self.exercise = exercise
        self.submission = submission
        self.chat_history = chat_history


class CodeEditorChatDTO:
    def __init__(
        self,
        problem_statement: str,
        solution_repository: dict[str, str],
        template_repository: dict[str, str],
        test_repository: dict[str, str],
        chat_history: [IrisMessage],
    ):
        self.problem_statement = problem_statement
        self.solution_repository = solution_repository
        self.template_repository = template_repository
        self.test_repository = test_repository
        self.chat_history = chat_history


class CodeEditorAdaptDTO:
    def __init__(
        self,
        problem_statement: str,
        solution_repository: dict[str, str],
        template_repository: dict[str, str],
        test_repository: dict[str, str],
        instructions: str,
    ):
        self.problem_statement = problem_statement
        self.solution_repository = solution_repository
        self.template_repository = template_repository
        self.test_repository = test_repository
        self.chat_history = instructions


class HestiaDTO:
    def __init__(self, code_hint: CodeHint, exercise: ProgrammingExercise):
        self.code_hint = code_hint
        self.exercise = exercise
