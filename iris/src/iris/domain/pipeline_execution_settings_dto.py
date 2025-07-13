from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    variant: str = Field(default="default")
