from typing import Literal, Optional

from pydantic import BaseModel, Field

from iris.common.callback_token import CallbackToken


class PipelineExecutionSettingsDTO(BaseModel):
    """The settings Artemis sends with every pipeline run."""

    # The credential for this run's callbacks. Only ever sent back as Bearer; see CallbackToken.
    authentication_token: CallbackToken = Field(alias="authenticationToken")
    # The id of this run, not a secret. Artemis versions that do not send it use the token as run id.
    run_id: Optional[str] = Field(alias="runId", default=None)
    artemis_llm_selection: str = Field(alias="selection", default="CLOUD_AI")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    variant: str = Field(default="default")
    support_level: Literal["low", "moderate", "high"] = Field(
        alias="supportLevel", default="moderate"
    )
    stream_response: bool = Field(alias="streamResponse", default=False)

    def is_local(self):
        return self.artemis_llm_selection == "LOCAL_AI"

    @property
    def callback_run_id(self) -> str:
        """The run id to put into callback URLs, logs and traces."""
        return self.run_id or self.authentication_token.reveal()
