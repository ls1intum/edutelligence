from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    artemis_llm_selection: str = Field(alias="selection", default="CLOUD_AI")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    variant: str = Field(default="default")
