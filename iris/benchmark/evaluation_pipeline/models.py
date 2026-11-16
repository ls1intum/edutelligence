"""Data model of the benchmark: test cases, Iris responses and assessments."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ChatMode(StrEnum):
    """Chat modes of Iris (same values as IrisChatMode in Pyris)."""

    COURSE = "COURSE_CHAT"
    LECTURE = "LECTURE_CHAT"
    PROGRAMMING_EXERCISE = "PROGRAMMING_EXERCISE_CHAT"
    TEXT_EXERCISE = "TEXT_EXERCISE_CHAT"


class Message(BaseModel):
    """One message of the conversation."""

    sender: Literal["student", "iris"]
    text: str


class User(BaseModel):
    """The student (pseudonymised)."""

    id: int
    language: str = "en"  # Artemis UI language of the student, e.g. "en" or "de"


class Course(BaseModel):
    """The course the conversation belongs to."""

    id: int
    name: str
    description: Optional[str] = None


class Exercise(BaseModel):
    """The exercise the conversation is about."""

    id: int
    title: str
    problem_statement: Optional[str] = None
    programming_language: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None  # due date
    max_points: Optional[float] = None
    # file path -> file content
    template_repository: dict[str, str] = Field(default_factory=dict)
    solution_repository: dict[str, str] = Field(default_factory=dict)


class Feedback(BaseModel):
    """One feedback item of a result, e.g. a test case."""

    test_case_name: Optional[str] = None
    text: Optional[str] = None
    credits: float = 0
    passed: Optional[bool] = None  # None = not executed


class Result(BaseModel):
    """The latest automatic assessment of the submission (test results)."""

    completion_date: Optional[datetime] = None
    successful: bool = False
    feedbacks: list[Feedback] = Field(default_factory=list)


class Submission(BaseModel):
    """The student's code at the time of the message."""

    id: int
    date: Optional[datetime] = None
    # file path -> file content, like the repository field Pyris receives
    repository: dict[str, str] = Field(default_factory=dict)
    build_failed: bool = False
    build_log: list[str] = Field(default_factory=list)
    latest_result: Optional[Result] = None


class TestCase(BaseModel):
    """A conversation that ends with a student message Iris has to answer."""

    id: int
    name: str
    description: str = ""
    chat_mode: ChatMode
    # taxonomy codes of the last student message: dimension -> characteristic
    characteristics: dict[str, str] = Field(default_factory=dict)
    user: User
    course: Course
    conversation: list[Message]
    exercise: Optional[Exercise] = None
    submission: Optional[Submission] = None

    @model_validator(mode="after")
    def ends_with_student_message(self):
        if not self.conversation or self.conversation[-1].sender != "student":
            raise ValueError("the conversation must end with a student message")
        return self


class TestDataset(BaseModel):
    """A versioned selection of test cases, referenced by their IDs."""

    id: int
    name: str
    version: str
    description: str = ""
    test_case_ids: list[int]


class TestCaseResult(BaseModel):
    """The response of Iris to one test case."""

    test_case_id: int
    response: Optional[str] = None
    error: Optional[str] = None


class Rating(StrEnum):
    """Three-level scale (Maurya et al. 2025) plus not applicable."""

    YES = "yes"
    TO_SOME_EXTENT = "to_some_extent"
    NO = "no"
    NOT_APPLICABLE = "not_applicable"


class CriterionScore(BaseModel):
    """The rating of one assessment criterion."""

    criterion: str
    rating: Rating
    reasoning: str = ""


class Assessment(BaseModel):
    """The judge's assessment of one test case result."""

    test_case_id: int
    scores: list[CriterionScore]


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class BenchmarkRun(BaseModel):
    """One execution of a test dataset against an Iris configuration."""

    id: str
    dataset_id: int
    dataset_version: str
    iris: str  # which Iris Response Service answered, e.g. "stub"
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: RunStatus = RunStatus.RUNNING
    results: list[TestCaseResult] = Field(default_factory=list)


class EvaluationRun(BaseModel):
    """One assessment of the results of a benchmark run by a judge model."""

    benchmark_run_id: str
    judge_model: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: RunStatus = RunStatus.RUNNING
    assessments: list[Assessment] = Field(default_factory=list)
