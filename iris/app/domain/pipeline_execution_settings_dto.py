from typing import List

from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    allowed_model_identifiers: List[str] = Field(alias="allowedModelIdentifiers")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
