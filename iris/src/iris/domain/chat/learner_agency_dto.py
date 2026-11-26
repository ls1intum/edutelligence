"""Wire type binding an offer of the solution workflow to the exercise it was made for."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SolutionChoice = Literal["TRY_MYSELF", "SHOW_SOLUTION", "SUMMARIZE", "SKIP_SUMMARY"]


class SolutionOffer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["solution-offer"] = "solution-offer"
    chat_mode: str = Field(alias="chatMode")
    entity_id: int = Field(alias="entityId")
    # The buttons, in order; Artemis accepts only these choices for the offer.
    choices: list[SolutionChoice]
