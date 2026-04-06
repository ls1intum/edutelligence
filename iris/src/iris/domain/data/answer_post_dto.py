from typing import Optional

from pydantic import BaseModel, Field


class AnswerPostDTO(BaseModel):
    id: int
    content: Optional[str] = None
    resolves_post: Optional[bool] = Field(None, alias="resolvesPost")
    user_id: int = Field(alias="userID")
    redacted: bool = False
