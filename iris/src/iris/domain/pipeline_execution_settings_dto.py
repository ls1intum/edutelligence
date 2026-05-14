from typing import Literal

from pydantic import BaseModel, Field


class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    artemis_llm_selection: str = Field(alias="selection", default="CLOUD_AI")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    variant: str = Field(default="default")
    support_level: Literal["low", "moderate", "high"] = Field(
        alias="supportLevel", default="moderate"
    )

    def is_local(self):
        return self.artemis_llm_selection == "LOCAL_AI"
