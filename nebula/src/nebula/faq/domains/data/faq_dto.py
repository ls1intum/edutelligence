from enum import Enum

from pydantic import BaseModel, Field
from typing import List, Set


class FaqState(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PROPOSED = "PROPOSED"

class FaqDTO(BaseModel):
    faq_id: int = Field(alias="id")
    question_title: str = Field(alias="questionTitle")
    question_answer: str = Field(alias="questionAnswer")
    categories: Set[str] = Field(default_factory=set)
    faq_state: FaqState = Field(alias="faqState")


class FaqRewritingDTO(BaseModel):
    user_id: int = Field(alias="userId")
    course_id: int = Field(alias="courseId")
    to_be_rewritten: str = Field(alias="toBeRewritten")
    faqs: List[FaqDTO]

class FaqRewritingResponse(BaseModel):
    rewritten_text: str = Field(alias="rewrittenText")
    user_id: int = Field(alias="userId")
    course_id: int = Field(alias="courseId")
