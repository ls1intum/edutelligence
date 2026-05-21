from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class MedBaseModel(BaseModel):
    """Base model matching the µEd API's camelCase JSON style."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class ArtefactType(str, Enum):
    TEXT = "TEXT"
    CODE = "CODE"
    MODEL = "MODEL"
    MATH = "MATH"
    OTHER = "OTHER"


class Detail(str, Enum):
    BRIEF = "BRIEF"
    MEDIUM = "MEDIUM"
    DETAILED = "DETAILED"


class Tone(str, Enum):
    FORMAL = "FORMAL"
    NEUTRAL = "NEUTRAL"
    FRIENDLY = "FRIENDLY"


class UserPreference(MedBaseModel):
    detail: Detail | None = None
    tone: Tone | None = None
    language: str | None = None


class User(MedBaseModel):
    user_id: str | None = None
    type: str
    preference: UserPreference | None = None
    task_progress: dict[str, Any] | None = None


class Task(MedBaseModel):
    task_id: str | None = None
    title: str | None = None
    content: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    learning_objectives: list[str] | None = None
    reference_solution: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class Submission(MedBaseModel):
    submission_id: str | None = None
    task_id: str | None = None
    type: ArtefactType
    format: str | None = None
    content: dict[str, Any]
    submitted_at: datetime | None = None
    version: int | None = None


class Criterion(MedBaseModel):
    criterion_id: str | None = None
    name: str
    context: str | dict[str, Any] | None = None
    grade_config: dict[str, Any] | None = None
    max_points: float | None = None


class PreSubmissionFeedback(MedBaseModel):
    enabled: bool


class LLMConfiguration(MedBaseModel):
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = None
    credentials: dict[str, Any] | None = None


class Configuration(MedBaseModel):
    llm: LLMConfiguration | None = None
    data_policy: dict[str, Any] | None = None
    execution_policy: dict[str, Any] | None = None


class EvaluateRequest(MedBaseModel):
    task: Task | None = None
    submission: Submission
    user: User | None = None
    criteria: list[Criterion] | None = None
    pre_submission_feedback: PreSubmissionFeedback | None = None
    callback_url: AnyUrl | None = None
    configuration: Configuration | None = None


class FeedbackTarget(MedBaseModel):
    artefact_type: ArtefactType
    format: str | None = None
    locator: dict[str, Any] | None = None


class EvaluateFeedback(MedBaseModel):
    feedback_id: str | None = None
    title: str | None = None
    message: str | None = None
    suggested_action: str | None = None
    awarded_points: float | None = None
    criterion: Criterion | None = None
    target: FeedbackTarget | None = None


class HealthStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class DataPolicySupport(str, Enum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    PARTIAL = "PARTIAL"


class EvaluateRequirements(MedBaseModel):
    requires_authorization_header: bool | None = None
    requires_llm_configuration: bool | None = None
    requires_llm_credential_proxy: bool | None = None


class ArtefactProfile(MedBaseModel):
    type: ArtefactType
    supported_formats: list[str] | None = None
    content_schema: dict[str, Any] | None = None
    locator_schema: dict[str, Any] | None = None


class EvaluateCapabilities(MedBaseModel):
    supports_evaluate: bool
    supports_pre_submission_feedback: bool
    supports_formative_feedback: bool
    supports_summative_feedback: bool
    supports_data_policy: DataPolicySupport
    supported_artefact_profiles: list[ArtefactProfile] | None = None
    supported_languages: list[str] | None = None
    supported_api_versions: list[str] | None = None


class EvaluateHealthResponse(MedBaseModel):
    status: HealthStatus
    message: str | None = None
    version: str | None = None
    requirements: EvaluateRequirements | None = None
    capabilities: EvaluateCapabilities


class ErrorResponse(MedBaseModel):
    title: str
    message: str | None = None
    code: str | None = None
    trace: str | None = None
    details: dict[str, Any] | None = None
