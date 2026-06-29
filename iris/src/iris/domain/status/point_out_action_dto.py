from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PointOutActionDTO(BaseModel):
    """A navigation action telling Artemis to point the student to a specific
    position in the lecture combined view they are currently looking at.

    Produced by the ``show_in_combined_view`` tool and sent to Artemis alongside
    the final chat result. Artemis persists it as a COMMAND message (a clickable
    marker in the chat history) and, if the combined view is still open, navigates
    the client to the given page / timestamp.
    """

    model_config = ConfigDict(populate_by_name=True)

    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)
    page: Optional[int] = Field(default=None, ge=1)  # PDF pages start at 1
    timestamp: Optional[float] = Field(default=None, ge=0)  # video time in seconds
    lecture_unit_name: Optional[str] = Field(alias="lectureUnitName", default=None)
    reason: Optional[str] = None
