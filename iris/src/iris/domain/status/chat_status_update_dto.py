from typing import List, Literal, Optional

from pydantic import Field

from iris.domain.chat.learner_agency_dto import SolutionOffer
from iris.domain.data.compaction_dto import CompactionDTO
from iris.domain.status.activity_dto import ActivityDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.domain.status.suggested_context_dto import SuggestedContextDTO


class ChatStatusUpdateDTO(StatusUpdateDTO):
    """Status update that Pyris sends to Artemis while a chat run is in progress."""

    result: Optional[str] = None
    solution_offer: Optional[SolutionOffer] = Field(alias="solutionOffer", default=None)
    # The choice Pyris read from a typed reply to the offer; Artemis stores it like a click.
    solution_choice: Optional[
        Literal["TRY_MYSELF", "SHOW_SOLUTION", "SUMMARIZE", "SKIP_SUMMARY"]
    ] = Field(alias="solutionChoice", default=None)
    final: Optional[bool] = Field(alias="final", default=None)
    partial_result: Optional[str] = Field(alias="partialResult", default=None)
    partial_seq: Optional[int] = Field(alias="partialSeq", default=None)
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    suggestions: Optional[List[str]] = Field(default_factory=list)
    activities: Optional[List[ActivityDTO]] = None
    activity_seq: Optional[int] = Field(alias="activitySeq", default=None)
    # The steps that ran since the previous assistant message of this run. Artemis
    # saves them on the message this update carries, so each message shows its own
    # steps. ``activities`` stays the whole run, for the live view.
    message_activities: Optional[List[ActivityDTO]] = Field(
        alias="messageActivities", default=None
    )
    suggested_context: Optional[SuggestedContextDTO] = Field(
        alias="suggestedContext", default=None
    )
    compaction: Optional[CompactionDTO] = None
