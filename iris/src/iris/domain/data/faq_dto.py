from typing import Optional

from pydantic import BaseModel, Field


class FaqDTO(BaseModel):
    """An FAQ as Artemis sends it for ingestion and deletion.

    Artemis omits empty values, so an FAQ without an answer arrives without ``questionAnswer``, and
    a deletion of an FAQ that no longer exists
    in Artemis carries only the ids. The fingerprint is sent by Artemis versions that reconcile FAQs
    and stored as the row's stamp.
    """

    faq_id: int = Field(alias="faqId")
    course_id: int = Field(alias="courseId")
    question_title: str = Field(default="", alias="questionTitle")
    question_answer: str = Field(default="", alias="questionAnswer")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
    content_fingerprint: Optional[str] = Field(default=None, alias="contentFingerprint")
