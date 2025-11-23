from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    artemis_llm_selection: str = Field(alias="selection")
    artemis_base_url: str = "http://localhost:9000" # Field(alias="artemisBaseUrl")
    variant: str = Field(default="default_local")
