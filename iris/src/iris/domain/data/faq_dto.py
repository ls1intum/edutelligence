from pydantic import BaseModel, Field


class FaqDTO(BaseModel):
    faq_id: int = Field(alias="faqId")
    course_id: int = Field(alias="courseId")
    question_title: str = Field(alias="questionTitle")
    question_answer: str = Field(alias="questionAnswer")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
