from typing import Optional

from pydantic import BaseModel, Field


class CourseDTO(BaseModel):
    id: int
    name: Optional[str]
    description: Optional[str] = Field(None)
