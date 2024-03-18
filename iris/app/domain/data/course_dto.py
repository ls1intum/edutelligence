from typing import Optional

from pydantic import BaseModel


class CourseDTO(BaseModel):
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
