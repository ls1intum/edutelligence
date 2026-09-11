from typing import Optional

from pydantic import BaseModel, Field


class AnswerPostDTO(BaseModel):
    id: int
    content: Optional[str] = None
    resolves_post: Optional[bool] = Field(None, alias="resolvesPost")
    user_id: int = Field(alias="userID")
    redacted: bool = False
    # Course role of the author: IRIS / INSTRUCTOR / TUTOR / STUDENT. Lets Iris tell a
    # student's follow-up, a tutor's answer, and its own earlier draft apart. ``None``
    # when Artemis could not resolve it.
    author_role: Optional[str] = Field(default=None, alias="authorRole")
