from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PointOutCommandDTO(BaseModel):
    """A command telling Artemis to point the student to a specific position in the lecture
    combined view they are currently looking at.

    Produced by the combined-view point-out feature and sent synchronously to Artemis mid-pipeline.
    Artemis navigates the client if the combined view is still open and replies whether it was
    carried out (see ``CommandResultDTO``). The ``type`` discriminator selects the command variant
    on the Artemis side.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: str = "pointOut"
    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)
    page: Optional[int] = Field(default=None, ge=1)  # PDF pages start at 1
    timestamp: Optional[float] = Field(default=None, ge=0)  # video time in seconds
