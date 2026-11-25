"""Wire type binding a solution offer to the exercise it was made for."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SolutionOffer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["solution-offer"] = "solution-offer"
    chat_mode: str = Field(alias="chatMode")
    entity_id: int = Field(alias="entityId")
