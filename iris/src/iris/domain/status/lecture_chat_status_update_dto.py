from typing import Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO


class LectureChatStatusUpdateDTO(StatusUpdateDTO):
    """Data Transfer Object for lecture chat status updates.
    This DTO extends the base StatusUpdateDTO to include the result of lecture chat
    pipeline operations, facilitating communication between Artemis and the lecture
    chat system.
    """

    result: str
    """The result message or status of the lecture chat pipeline operation."""
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
