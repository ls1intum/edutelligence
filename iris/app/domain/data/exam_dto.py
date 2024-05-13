from datetime import datetime

from pydantic import BaseModel, Field


class ExamDTO(BaseModel):
    id: int = Field(alias="id")
    title: str = Field(alias="title")
    is_text_exam: bool = Field(alias="isTextExam")
    start_date: datetime = Field(alias="startDate")
    end_date: datetime = Field(alias="endDate")
    publish_results_date: datetime = Field(alias="publishResultsDate")
    exam_student_review_start: datetime = Field(alias="examStudentReviewStart")
    exam_student_review_end: datetime = Field(alias="examStudentReviewEnd")
