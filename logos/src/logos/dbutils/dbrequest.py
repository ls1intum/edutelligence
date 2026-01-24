from typing import Optional, Union

from pydantic import BaseModel


class LogosKeyModel(BaseModel):
    logos_key: str


class LogosSetupRequest(BaseModel):
    base_url: str
    provider_name: str
    provider_type: str


class SetLogRequest(LogosKeyModel):
    set_log: str
    process_id: int


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


class AddProfileRequest(LogosKeyModel):
    profile_name: str
    process_id: int


class GetRole(LogosKeyModel):
    pass


class ConnectProcessProviderRequest(LogosKeyModel):
    profile_id: int
    provider_id: int


class ConnectProcessModelRequest(LogosKeyModel):
    profile_id: int
    model_id: int


class ConnectProfileModelRequest(LogosKeyModel):
    profile_id: int
    model_id: int


class ConnectServiceProcessRequest(LogosKeyModel):
    service_id: int
    process_name: str


class ConnectModelProviderRequest(LogosKeyModel):
    model_id: int
    provider_id: int


class ConnectModelApiRequest(LogosKeyModel):
    model_id: int
    provider_id: int
    api_key: str


class AddModelRequest(LogosKeyModel):
    name: str
    endpoint: str


class AddFullModelRequest(LogosKeyModel):
    name: str
    endpoint: str
    weight_privacy: str
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
    entity_id: int
    name: str
    description: str
    threshold_privacy: str
    threshold_latency: int
    threshold_accuracy: int
    threshold_cost: int
    threshold_quality: int
    priority: int
    topic: str


class UpdatePolicyRequest(LogosKeyModel):
    id: int
    entity_id: int
    name: str
    description: str
    threshold_privacy: str
    threshold_latency: int
    threshold_accuracy: int
    threshold_cost: int
    threshold_quality: int
    priority: int
    topic: str


class DeletePolicyRequest(LogosKeyModel):
    id: int


class GetPolicyRequest(LogosKeyModel):
    id: int


class AddServiceRequest(LogosKeyModel):
    name: str


class GetProcessIdRequest(LogosKeyModel):
    pass


class GetImportDataRequest(LogosKeyModel):
    json_data: dict


class AddBillingRequest(LogosKeyModel):
    type_name: str
    type_cost: float
    valid_from: str
