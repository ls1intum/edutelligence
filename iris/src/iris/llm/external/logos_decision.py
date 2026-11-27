"""Yes/no decisions through the Logos /v1/systemone endpoint: one forward pass, no generated text."""

from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm.external.model import LanguageModel


class _Answer(BaseModel):
    noul: float = Field(ge=0, le=1)


class _Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class _Response(BaseModel):
    answers: dict[str, _Answer]
    usage: _Usage | None = None


class LogosDecisionModel(LanguageModel):
    """Returns the probability that the answer to a question about a state is yes."""

    type: Literal["logos_decision"]
    base_url: str
    api_key: str = Field(repr=False, exclude=True)
    request_timeout_seconds: float = Field(default=15, gt=0)
    # Persistent connection pool: the call runs before every classified message.
    _client: httpx.Client
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.request_timeout_seconds,
        )

    def decide(self, state: str, question: str) -> tuple[float, TokenUsageDTO]:
        response = self._client.post(
            "/systemone",
            json={
                "model": self.model,
                "state": state,
                "questions": {"answer": {"type": "noul", "instructions": question}},
            },
        )
        response.raise_for_status()
        result = _Response.model_validate(response.json())
        usage = TokenUsageDTO(model=self.model)
        if result.usage is not None:
            usage.num_input_tokens = result.usage.input_tokens
            usage.num_output_tokens = result.usage.output_tokens
            usage.usage_reported = True
        return result.answers["answer"].noul, usage
