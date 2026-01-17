from typing import List, Optional

from memiris import MemoryDTO
from pydantic import Field

from iris.domain.citation import CitationDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


class LectureChatStatusUpdateDTO(StatusUpdateDTO):
    """Data Transfer Object for lecture chat status updates.

    This DTO extends the base StatusUpdateDTO to include the result of lecture chat
    pipeline operations, facilitating communication between Artemis and the lecture
    chat system. Aligned with CourseChatStatusUpdateDTO for memiris support.
    """

    # result has to be optional now because now also done messages for memiris work are sent
    # -> those have no content for result -> have to be distinguishable
    result: Optional[str] = None
    """The result message or status of the lecture chat pipeline operation."""
    suggestions: List[str] = []
    """Suggested follow-up questions or prompts for the user."""
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    """The title of the chat session."""
    accessed_memories: List[MemoryDTO] = Field(alias="accessedMemories", default=[])
    """Memories that were accessed during this interaction."""
    created_memories: List[MemoryDTO] = Field(alias="createdMemories", default=[])
    """Memories that were created during this interaction."""
    citations: List[CitationDTO] = []
    """Structured citations for the response."""
