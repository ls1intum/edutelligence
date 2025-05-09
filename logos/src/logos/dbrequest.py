from pydantic import BaseModel


class LogosKeyModel(BaseModel):
    logos_key: str


class AddProviderRequest(LogosKeyModel):
    provider_name: str
    base_url: str
    api_key: str
    auth_name: str
    auth_format: str


class AddProfileRequest(LogosKeyModel):
    profile_name: str
    process_id: int


class ConnectProcessProviderRequest(LogosKeyModel):
    profile_id: int
    api_id: int


class ConnectProcessModelRequest(LogosKeyModel):
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
    api_id: int


class AddModelRequest(LogosKeyModel):
    name: str
    endpoint: str


class AddServiceRequest(LogosKeyModel):
    name: str


class GetProcessIdRequest(LogosKeyModel):
    pass


class GetAPIIdRequest(LogosKeyModel):
    api_key: str
