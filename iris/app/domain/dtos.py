from pydantic import BaseModel

from domain import (
    Course,
    ProgrammingExercise,
    IrisMessage,
    ProgrammingSubmission,
    CodeHint,
)


class ProgrammingExerciseTutorChatDTO(BaseModel):
    course: Course
    exercise: ProgrammingExercise
    submission: ProgrammingSubmission
    chat_history: [IrisMessage]

    def __str__(self):
        return (
            f"ProgrammingExerciseTutorChatDTO(course={self.course}, exercise={self.exercise}, "
            f"submission={self.submission}, chat_history={self.chat_history})"
        )


class CodeEditorChatDTO(BaseModel):
    problem_statement: str
    solution_repository: dict[str, str]
    template_repository: dict[str, str]
    test_repository: dict[str, str]
    chat_history: [IrisMessage]

    def __str__(self):
        return (
            f'CodeEditorChatDTO(problem_statement="{self.problem_statement}", '
            f"solution_repository={self.solution_repository}, template_repository={self.template_repository}, "
            f"test_repository={self.test_repository}, chat_history={self.chat_history})"
        )


class CodeEditorAdaptDTO(BaseModel):
    problem_statement: str
    solution_repository: dict[str, str]
    template_repository: dict[str, str]
    test_repository: dict[str, str]
    instructions: str

    def __str__(self):
        return (
            f'CodeEditorAdaptDTO(problem_statement="{self.problem_statement}", '
            f"solution_repository={self.solution_repository}, template_repository={self.template_repository}, "
            f'test_repository={self.test_repository}, instructions="{self.instructions}")'
        )


class HestiaDTO(BaseModel):
    code_hint: CodeHint
    exercise: ProgrammingExercise

    def __str__(self):
        return f"HestiaDTO(code_hint={self.code_hint}, exercise={self.exercise})"
