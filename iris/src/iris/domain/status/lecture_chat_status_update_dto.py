from typing import Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO

# this class is at a different place in the directory as the course pendant
# course pendant has some additional memiris attributes


class LectureChatStatusUpdateDTO(StatusUpdateDTO):
    """Data Transfer Object for lecture chat status updates.
    This DTO extends the base StatusUpdateDTO to include the result of lecture chat
    pipeline operations, facilitating communication between Artemis and the lecture
    chat system.
    """

    # result has to be optional now because now also done messages for memiris work are sent -> those have no content
    # for result -> have to be distinguishable
    result: Optional[str] = None
    """The result message or status of the lecture chat pipeline operation."""
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
