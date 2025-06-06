from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from iris.domain.data.course_dto import CourseDTO


class TextExerciseDTO(BaseModel):
    id: int
    title: str
    course: CourseDTO
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
