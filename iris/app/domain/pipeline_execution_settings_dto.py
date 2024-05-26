from typing import List, Optional

from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    allowed_model_identifiers: Optional[List[str]] = Field(alias="allowedModelIdentifiers", default=[])
    artemis_base_url: str = Field(alias="artemisBaseUrl")
