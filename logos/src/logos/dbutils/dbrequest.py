from typing import Any, Optional, Union

from pydantic import BaseModel, Field

CSV_HEADER_PRENAME = "prename"
CSV_HEADER_NAME    = "name"
CSV_HEADER_EMAIL   = "email"
CSV_HEADER_TEAM    = "team"
REQUIRED_CSV_HEADERS = frozenset({
    CSV_HEADER_PRENAME,
    CSV_HEADER_NAME,
    CSV_HEADER_EMAIL,
    CSV_HEADER_TEAM,
})


class LogosKeyModel(BaseModel):
    logos_key: str


class LogosSetupRequest(BaseModel):
    base_url: str
    provider_name: str
    provider_type: str


class SetLogRequest(LogosKeyModel):
    set_log: str
    api_key_id: int


class AddServiceProxyRequest(LogosKeyModel):
    base_url: str
    provider_name: str
    provider_type: str


class AddProviderRequest(LogosKeyModel):
    provider_name: str
    base_url: str
    api_key: str
    auth_name: str
    auth_format: str
    provider_type: str
    cloud_provider_type: Optional[str] = None
    privacy_level: str


class UpdateProviderRequest(LogosKeyModel):
    provider_id: int
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    auth_name: Optional[str] = None
    auth_format: Optional[str] = None
    provider_type: Optional[str] = None
    cloud_provider_type: Optional[str] = None
    privacy_level: Optional[str] = None


class DeleteProviderRequest(LogosKeyModel):
    provider_id: int


class UpdateProviderSdiConfigRequest(LogosKeyModel):
    provider_id: int
    ollama_admin_url: str | None = None
    total_vram_mb: int | None = None
    parallel_capacity: int | None = None
    keep_alive_seconds: int | None = None
    max_loaded_models: int | None = None


class GetRole(LogosKeyModel):
    pass


class ConnectApiKeyProviderRequest(LogosKeyModel):
    api_key_id: int
    provider_id: int


class ConnectApiKeyModelRequest(LogosKeyModel):
    api_key_id: int
    model_id: int


class ConnectApplicationKeyRequest(LogosKeyModel):
    team_id: int
    key_name: str
    environment: str = ""


class ConnectModelProviderRequest(LogosKeyModel):
    model_id: int
    provider_id: int


class ConnectModelApiRequest(LogosKeyModel):
    model_id: int
    provider_id: int
    api_key: str
    endpoint: str = ""


class AddModelRequest(LogosKeyModel):
    name: str
    tags: Optional[str] = ""
    parallel: Optional[int] = 1
    worse_latency: Optional[int] = None
    worse_accuracy: Optional[int] = None
    worse_cost: Optional[int] = None
    worse_quality: Optional[int] = None
    description: Optional[str] = ""

class UpdateModelInfoRequest(LogosKeyModel):
    model_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    parallel: Optional[int] = None
    weight_latency: Optional[int] = None
    weight_accuracy: Optional[int] = None
    weight_cost: Optional[int] = None
    weight_quality: Optional[int] = None

class AddFullModelRequest(LogosKeyModel):
    name: str
    worse_accuracy: Union[int, None]
    worse_quality: Union[int, None]
    worse_latency: Union[int, None]
    worse_cost: Union[int, None]
    tags: str
    parallel: int
    description: str


class GiveFeedbackRequest(LogosKeyModel):
    id: int
    category: str
    value: Union[str, int]


class DeleteModelRequest(LogosKeyModel):
    id: int


class GetModelRequest(LogosKeyModel):
    id: int


class AddPolicyRequest(LogosKeyModel):
    name: str
    description: str
    threshold_privacy: str
    threshold_latency: int
    threshold_accuracy: int
    threshold_cost: int
    threshold_quality: int
    priority: int
    topic: str
    api_key_id: Optional[int] = None
    team_id: Optional[int] = None


class UpdatePolicyRequest(LogosKeyModel):
    id: int
    name: str
    description: str
    threshold_privacy: str
    threshold_latency: int
    threshold_accuracy: int
    threshold_cost: int
    threshold_quality: int
    priority: int
    topic: str
    api_key_id: Optional[int] = None
    team_id: Optional[int] = None


class DeletePolicyRequest(LogosKeyModel):
    id: int


class GetPolicyRequest(LogosKeyModel):
    id: int


class GetApiKeyIdRequest(LogosKeyModel):
    pass


class GetImportDataRequest(LogosKeyModel):
    json_data: dict


class AddBillingRequest(LogosKeyModel):
    type_name: str
    type_cost: float
    valid_from: str
    model_id: Optional[int] = None


class LogosNodeAuthRequest(BaseModel):
    shared_key: str
    capabilities_models: list[str] = Field(default_factory=list)


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

class UpdateRoleRequest(BaseModel):
    role: str

class CreateUserRequest(BaseModel):
    prename: str
    name: str
    email: Optional[str] = None
    role: str
    team_ids: list[int] = []

class CreateTeamRequest(BaseModel):
    name: str
    owner_ids: list[int] = []
    default_cloud_rpm_limit: Optional[int] = None
    default_cloud_tpm_limit: Optional[int] = None
    default_local_rpm_limit: Optional[int] = None
    default_local_tpm_limit: Optional[int] = None
    default_monthly_budget_micro_cents: Optional[int] = None
    team_monthly_budget_micro_cents: Optional[int] = None

class AddTeamMemberRequest(BaseModel):
    user_id: int
    is_owner: bool = False

class SetOwnerRequest(BaseModel):
    is_owner: bool


class CreateApiKeyRequest(BaseModel):
    name: str
    key_type: str = "developer"
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    environment: str = ""
    log: str = "BILLING"
    settings: Optional[dict] = None
    default_priority: int = 1


class SetApiKeyModelPermissionsRequest(BaseModel):
    model_ids: list[int]


class SetTeamModelPermissionsRequest(BaseModel):
    model_ids: list[int]


class UpdateApiKeyRequest(BaseModel):
    environment: Optional[str] = None
    default_priority: Optional[int] = None
    log: Optional[str] = None
    budget_limit_micro_cents: Optional[int] = None
    cloud_rpm_limit: Optional[int] = None
    cloud_tpm_limit: Optional[int] = None
    local_rpm_limit: Optional[int] = None
    local_tpm_limit: Optional[int] = None


class UpdateTeamRequest(BaseModel):
    default_cloud_rpm_limit: Optional[int] = None
    default_cloud_tpm_limit: Optional[int] = None
    default_local_rpm_limit: Optional[int] = None
    default_local_tpm_limit: Optional[int] = None
    default_monthly_budget_micro_cents: Optional[int] = None
    team_monthly_budget_micro_cents: Optional[int] = None

class UpdateTeamNameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

class UpdateUserInfoRequest(BaseModel):
    prename: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None

class CreateAppKeyEndpointRequest(BaseModel):
    name: str
    key_type: str = "application"
    environment: str = "-"
    default_priority: int = 0
    log: str = "BILLING"
    settings: Optional[dict] = None