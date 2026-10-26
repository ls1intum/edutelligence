from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from logos.benchmarks.configuration import BenchmarkBatch, BenchmarkSettings
from logos.dbutils.dbmodules import ThresholdLevel


class LogosKeyModel(BaseModel):
    logos_key: str


class NightlyStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_provider_id: int = Field(gt=0)


class NightlyUpdateRequest(NightlyStatusRequest):
    enabled: StrictBool
    expected_enabled: StrictBool


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator("query", mode="before")
    @classmethod
    def _strip_query(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


# A free-form text field of the decision API: a string, or JSON rendered as text.
DecisionText = Union[str, dict, list, None]


class NoulCriteria(BaseModel):
    true: DecisionText = None
    false: DecisionText = None


class NoulQuestion(BaseModel):
    type: Literal["noul"]
    instructions: DecisionText = None
    criteria: Optional[NoulCriteria] = None


class ChoiceQuestion(BaseModel):
    type: Literal["choice"]
    instructions: DecisionText = None
    criteria: dict[str, DecisionText]


class ScoreQuestion(BaseModel):
    type: Literal["score"]
    instructions: DecisionText = None
    criteria: list[Union[str, dict, list]] = Field(min_length=1)


DecisionQuestion = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion], Field(discriminator="type")]


# Upper bound on questions per /v1/systemone call. Each entry becomes one
# pipeline completion; without a cap a single request can spawn unbounded
# concurrent auth/schedule/DB work before per-turn rate limits apply.
SYSTEM_ONE_MAX_QUESTIONS = 32


class SystemOneRequest(BaseModel):
    """Body of ``POST /v1/systemone``: a state and the typed questions to answer about it."""

    model: str = Field(min_length=1)
    state: Any
    questions: dict[str, DecisionQuestion] = Field(min_length=1, max_length=SYSTEM_ONE_MAX_QUESTIONS)


class LogosNodeAuthRequest(BaseModel):
    shared_key: str
    capabilities_models: list[str] = Field(default_factory=list)
    configured_models: list[str] = Field(default_factory=list)


class LogosNodeRegisterRequest(LogosKeyModel):
    provider_name: str
    base_url: str = ""
    # Required, deliberately without a default. LOCAL is the *most* trusted tier
    # ("our datacentre"), so defaulting to it would silently make every
    # self-registering worker eligible for traffic restricted to
    # operator-controlled hardware — including a rented GPU or a personal Mac
    # running the MLX worker, which belong in THIRD_PARTY_HARDWARE. The caller
    # has to state the trust level; there is no safe value to assume on its
    # behalf. Costless to require now because the endpoint has been returning
    # 400 for every request, so it has no working callers to break.
    privacy_level: str

    @field_validator("privacy_level")
    @classmethod
    def _validate_privacy_level(cls, value: str) -> str:
        known = {level.value for level in ThresholdLevel}
        if value not in known:
            raise ValueError(f"privacy_level must be one of {sorted(known)}")
        return value


class LogosNodeStatusRequest(LogosKeyModel):
    provider_id: int


# Far above any node's model count; bounds what one request can write.
_MAX_PROFILE_MODELS = 1000


class LogosNodeLegacyProfileImport(BaseModel):
    model_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=_MAX_PROFILE_MODELS)
    unsupported_models: dict[str, str] = Field(default_factory=dict, max_length=_MAX_PROFILE_MODELS)


class LogosNodeModelProfilesRequest(BaseModel):
    shared_key: str
    # model name -> calibration key hash the worker computes for it right now
    calibration_key_hashes: dict[str, str] = Field(default_factory=dict, max_length=_MAX_PROFILE_MODELS)
    # model name -> GPUs the node can calibrate and serve the model on
    slice_gpu_counts: dict[str, int] = Field(default_factory=dict, max_length=_MAX_PROFILE_MODELS)
    legacy_import: LogosNodeLegacyProfileImport | None = None


class LogosNodeCalibrationReservationRequest(BaseModel):
    shared_key: str
    model_name: str
    # The key and GPU count the worker computed for the model just now; a
    # config edit may not have reached Logos through a status yet.
    calibration_key_hash: str | None = None
    slice_gpu_count: int | None = None


class LogosNodeClearUnsupportedRequest(LogosKeyModel):
    provider_id: int
    model_name: str


class LogosNodeResetProfilesRequest(LogosKeyModel):
    provider_id: int
    # None resets every profile of the node
    model_names: list[str] | None = None


class LogosNodeInvalidateCalibrationRequest(LogosKeyModel):
    calibration_id: int
    reason: str = "invalidated by admin"


class LogosNodeApplyLanesRequest(LogosKeyModel):
    provider_id: int
    lanes: list[dict[str, Any]]


class LogosNodeSleepLaneRequest(LogosKeyModel):
    provider_id: int
    lane_id: str
    level: int = 1
    mode: str = "wait"


class LogosNodeWakeLaneRequest(LogosKeyModel):
    provider_id: int
    lane_id: str


class LogosNodeDeleteLaneRequest(LogosKeyModel):
    provider_id: int
    lane_id: str


class LogosNodeReconfigureLaneRequest(LogosKeyModel):
    provider_id: int
    lane_id: str
    updates: dict[str, Any]


# Internal (secret-gated) endpoint request models, called by the Spring
# webservice after its own JWT validation.


class RefreshPipelineRequest(BaseModel):
    rebuild_classifier: bool = False
    # Set by the webservice when a provider itself changed, as opposed to a
    # model link or a permission. A newly added cloud provider has no models
    # until its /v1/models listing is read, and that otherwise waits for the
    # next interval tick — a quarter of an hour of an empty model list.
    sync_cloud_models: bool = False


class LaneLockChangedRequest(BaseModel):
    """A lane lock the webservice just committed, pushed so the planner applies it at once."""

    provider_id: int
    lane_id: str
    locked: bool
    # Order of the change among all changes of this lane; the pushes can
    # arrive out of order, so an older revision is ignored.
    revision: int
    # The lock's restore record as committed (JSON text, None for none). Sent
    # by webservices that know the record; a push without the field leaves
    # the record the planner holds.
    restore_lanes_json: Optional[str] = None


class InternalCalibrateRequest(BaseModel):
    provider_id: int


class InternalStopCalibrationRequest(BaseModel):
    provider_id: int


class InternalReleaseCalibrationClaimRequest(BaseModel):
    provider_id: int
    claim_token: str


class InternalReleaseRecoveryRequest(BaseModel):
    model_provider_id: int
    force: bool = False


class InternalDeleteLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalAddLaneRequest(BaseModel):
    provider_id: int
    lane: dict[str, Any]


class InternalLaneLoadStatusRequest(BaseModel):
    provider_id: int
    model: str


class InternalSleepLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalDrainLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalWakeLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalBenchmarkRequest(BenchmarkSettings):
    batch: BenchmarkBatch | None = None
    model_provider_id: int = Field(gt=0)
    samples: int = Field(default=5, gt=0, le=100)
    max_output_tokens: int = Field(default=512, gt=0, le=4096)


class DatasetSearchRequest(BaseModel):
    query: str = Field(default="", max_length=200)
    cursor: str | None = Field(default=None, max_length=4096)


class DatasetMetadataRequest(BaseModel):
    dataset: str = Field(max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    subset: str | None = Field(default=None, max_length=200)
    split: str | None = Field(default=None, max_length=100)


class BenchmarkLimitsRequest(BaseModel):
    model_provider_id: int = Field(gt=0)


class HfReachabilityRequest(BaseModel):
    hf_repo_id: str = Field(min_length=1, max_length=200)


class CancelClientTagRequest(BaseModel):
    tag: str = Field(min_length=1, max_length=200)
