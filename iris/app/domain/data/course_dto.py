from typing import Optional

from pydantic import BaseModel, Field
from datetime import datetime


class CourseDTO(BaseModel):
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    default_programming_language: Optional[str] = Field(
        None, alias="defaultProgrammingLanguage"
    )
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)

    def get_end_date(self):
        """
        Get the end date of the course in a human-readable format
        """
        return (
            self.end_date.strftime("%A %d. %B %Y") if self.end_date else "Not specified"
        )

    def get_start_date(self):
        """
        Get the start date of the course in a human-readable format
        """
        return (
            self.start_date.strftime("%A %d. %B %Y")
            if self.start_date
            else "Not specified"
        )

    def get_default_programming_language(self):
        return (
            self.default_programming_language
            if self.default_programming_language
            else "Not specified"
        )

    def is_online_course(self):
        return "Yes" if self.online_course else "No"
