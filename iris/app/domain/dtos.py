from typing import List

from pydantic import BaseModel

from domain import (
    Course,
    ProgrammingExercise,
    IrisMessage,
    ProgrammingSubmission,
    CodeHint,
)


class SettingsDTO(BaseModel):
    allowedModels: list[str]

    def __str__(self):
        return f"SettingsDTO(allowedModels={self.allowedModels})"


class BaseChatModel(BaseModel):
    query: IrisMessage
    chat_history: List[IrisMessage]
    settings: SettingsDTO

    def __str__(self):
        return f"BaseChatModel(query={self.query}, chat_history={self.chat_history})"


class ProgrammingExerciseTutorChatDTO(BaseChatModel):
    course: Course
    exercise: ProgrammingExercise
    submission: ProgrammingSubmission

    def __str__(self):
        return (
            f"ProgrammingExerciseTutorChatDTO(query={self.query}, course={self.course}, exercise={self.exercise}, "
            f"submission={self.submission}, settings={self.settings}, chat_history={self.chat_history})"
        )


class CodeEditorChatDTO(BaseChatModel):
    problem_statement: str
    solution_repository: dict[str, str]
    template_repository: dict[str, str]
    test_repository: dict[str, str]

    def __str__(self):
        return (
            f"CodeEditorChatDTO(problem_statement={self.problem_statement}, "
            f"solution_repository={self.solution_repository}, "
            f"template_repository={self.template_repository}, test_repository={self.test_repository}, "
            f"settings={self.settings}, chat_history={self.chat_history})"
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
