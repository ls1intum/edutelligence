from typing import List

from pydantic import BaseModel, Field

from iris.domain.data.answer_post_dto import AnswerPostDTO


class PostDTO(BaseModel):
    id: int
    content: str
    answers: List[AnswerPostDTO] = Field(default=[])
    user_id: int = Field(alias="userID")
