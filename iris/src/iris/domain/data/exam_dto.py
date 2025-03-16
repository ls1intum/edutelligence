from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ExamDTO(BaseModel):
    """ExamDTO represents an exam with properties such as title, exam type, start date, end date, publish results date,
     and exam student review periods."""
    id: int = Field(alias="id")
    title: Optional[str] = Field(alias="title", default=None)
    is_text_exam: bool = Field(alias="isTextExam", default=False)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
    publish_results_date: Optional[datetime] = Field(
        alias="publishResultsDate", default=None
    )
    exam_student_review_start: Optional[datetime] = Field(
        alias="examStudentReviewStart", default=None
    )
    exam_student_review_end: Optional[datetime] = Field(
        alias="examStudentReviewEnd", default=None
    )
