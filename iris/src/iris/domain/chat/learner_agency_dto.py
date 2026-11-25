"""Configuration and wire types for the learner agency workflow."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_usage_dto import TokenUsageDTO


class SolutionOffer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["solution-offer"] = "solution-offer"
    chat_mode: str = Field(alias="chatMode")
    entity_id: int = Field(alias="entityId")


@dataclass
class LearnerAgencyTurn:
    mode: Literal["normal", "offer", "hint", "solution"] = "normal"
    tokens: list[TokenUsageDTO] = field(default_factory=list)
