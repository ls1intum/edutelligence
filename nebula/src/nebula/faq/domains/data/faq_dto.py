from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Set

class FaqState(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PROPOSED = "PROPOSED"

class BaseDTO(BaseModel):
    class Config:
        populate_by_name = True


class FaqDTO(BaseDTO):
    faq_id: int = Field(alias="id")
    question_title: str = Field(alias="questionTitle")
    question_answer: str = Field(alias="questionAnswer")
    categories: Set[str] = Field(default_factory=set)
    faq_state: FaqState = Field(alias="faqState")


class FaqRewritingDTO(BaseDTO):
    to_be_rewritten: str = Field(alias="toBeRewritten")
    faqs: List[FaqDTO]

class FaqRewritingResponse(BaseDTO):
    rewritten_text: str = Field(alias="rewrittenText")

class FaqConsistencyDTO(BaseDTO):
    faqs: List[FaqDTO] = Field(alias="faqs")
    to_be_checked: str = Field(alias="toBeChecked")

class FaqConsistencyResponse(BaseDTO):
    consistent: bool = Field(alias="consistent")
    inconsistencies: List[str] = Field(default_factory=list)
    improvement: str = Field(alias="improvement")
    faqIds: List[int] = Field(alias="faqIds", default_factory=list)
