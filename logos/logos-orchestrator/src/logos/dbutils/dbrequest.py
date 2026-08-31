from typing import Any, Optional

from pydantic import BaseModel, Field


class LogosKeyModel(BaseModel):
    logos_key: str


class UpdateProviderSdiConfigRequest(LogosKeyModel):
    provider_id: int
    ollama_admin_url: str | None = None
    total_vram_mb: int | None = None
    parallel_capacity: int | None = None
    keep_alive_seconds: int | None = None
    max_loaded_models: int | None = None


class ConnectModelProviderRequest(LogosKeyModel):
    model_id: int
    provider_id: int
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


class LogosNodeAuthRequest(BaseModel):
    shared_key: str
    capabilities_models: list[str] = Field(default_factory=list)
    configured_models: list[str] = Field(default_factory=list)


class LogosNodeRegisterRequest(LogosKeyModel):
    provider_name: str
    base_url: str = ""


class LogosNodeStatusRequest(LogosKeyModel):
    provider_id: int


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


class InternalCalibrateRequest(BaseModel):
    provider_id: int


class InternalDeleteLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalAddLaneRequest(BaseModel):
    provider_id: int
    lane: dict[str, Any]


class InternalSleepLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalWakeLaneRequest(BaseModel):
    provider_id: int
    lane_id: str


class InternalBenchmarkRequest(BaseModel):
    model_provider_id: int = Field(gt=0)
    samples: int = Field(default=5, gt=0, le=100)
    max_output_tokens: int = Field(default=512, gt=0, le=4096)
