from typing import Literal, Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO

StruggleAction = Literal["silent", "ambient", "active"]


class StruggleInterventionStatusUpdateDTO(StatusUpdateDTO):
    """
    Result sent back to Artemis for a struggle-intervention run.
    - action: the proposed surface level (silent | ambient | active).
    - result: the Socratic hint message (None when action == silent).
    - confidence: 0.0-1.0 model confidence; Artemis applies the threshold.
    - rationale: logged, never shown to the student.
    """

    action: Optional[StruggleAction] = Field(default=None)
    result: Optional[str] = None
    confidence: Optional[float] = Field(default=None)
    rationale: Optional[str] = Field(default=None)
    anchor_file: Optional[str] = Field(default=None)
    anchor_line: Optional[int] = Field(default=None)
    inline_hint: Optional[str] = Field(default=None)
    # confirm_close mode
    resolved: Optional[bool] = None
    closing_sentence: Optional[str] = None
    episode_label: Optional[str] = None
    # stale_check mode
    ask: Optional[bool] = None
    question: Optional[str] = None
