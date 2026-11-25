"""Typed decisions through Logos' TypeSafe-compatible /v1/systemone endpoint."""

from typing import Literal

import httpx
from pydantic import BaseModel, Field, PrivateAttr

from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm.external.model import BooleanDecisionResult, DecisionModel


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)


class DecisionUsage(BaseModel):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class SystemOneResponse(BaseModel):
    model: str
    answers: dict[str, NoulAnswer]
    usage: DecisionUsage | None = None


class LogosDecisionModel(DecisionModel):
    """One native decision call, with no chat generation and no automatic retry."""

    type: Literal["logos_decision"]
    base_url: str
    api_key: str = Field(repr=False, exclude=True)
    request_timeout_seconds: float = Field(default=15, gt=0)
    _client: httpx.Client = PrivateAttr()

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.request_timeout_seconds,
        )

    def decide(self, state: str, instructions: str) -> BooleanDecisionResult:
        response = self._client.post(
            "systemone",
            json={
                "model": self.model,
                "state": state,
                "questions": {
                    "decision": {"type": "noul", "instructions": instructions}
                },
            },
        )
        response.raise_for_status()
        result = SystemOneResponse.model_validate(response.json())
        if result.model != self.model:
            raise ValueError("Decision response names a different model")
        answer = result.answers.get("decision")
        if answer is None:
            raise ValueError("Decision response is missing the requested answer")
        usage = TokenUsageDTO(model=self.model)
        if result.usage is not None:
            usage.num_input_tokens = result.usage.input_tokens
            usage.num_output_tokens = result.usage.output_tokens
            usage.usage_reported = True
        return BooleanDecisionResult(probability=answer.noul, token_usage=usage)
