from pydantic import BaseModel, Field
from typing import List


class FaqDTO(BaseModel):
    faq_id: int = Field(alias="faqId")
    question_title: str = Field(alias="questionTitle")
    question_answer: str = Field(alias="questionAnswer")

class FaqRewritingRequest(BaseModel):
    user_id: int = Field(alias="userId")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(alias="courseName")
    to_be_rewritten: str = Field(alias="toBeRewritten")
    faqs: List[FaqDTO]

class FaqRewritingResponse(BaseModel):
    rewritten_text: str = Field(alias="rewrittenText")
    user_id: int = Field(alias="userId")
    course_id: int = Field(alias="courseId")
