from typing import Any

from pydantic import BaseModel, Field, field_validator

from logos.benchmarks.configuration import BenchmarkBatch, BenchmarkSettings
from logos.dbutils.dbmodules import ThresholdLevel


class LogosKeyModel(BaseModel):
    logos_key: str


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
    legacy_import: LogosNodeLegacyProfileImport | None = None


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


class InternalCalibrateRequest(BaseModel):
    provider_id: int


class InternalStopCalibrationRequest(BaseModel):
    provider_id: int


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
