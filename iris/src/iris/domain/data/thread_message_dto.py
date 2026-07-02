from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ThreadMessageDTO(BaseModel):
    """A single message in a communication-channel thread.

    Used as the raw input the course-memory Q/A extractor reads. ``author_role``
    distinguishes student / tutor / iris so the extractor can identify the
    verified answer.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    author_role: str = Field(alias="authorRole")
    content: str
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    is_iris_draft: bool = Field(default=False, alias="isIrisDraft")
