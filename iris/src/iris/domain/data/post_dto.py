from typing import List, Optional

from pydantic import BaseModel, Field

from iris.domain.data.answer_post_dto import AnswerPostDTO


class PostDTO(BaseModel):
    id: int
    content: str
    # Ordered oldest first by Artemis. The order is meaningful: the last entry is the most
    # recent message in the thread and therefore the one that triggered this run.
    answers: List[AnswerPostDTO] = Field(default=[])
    user_id: int = Field(alias="userID")
    author_role: Optional[str] = Field(default=None, alias="authorRole")
