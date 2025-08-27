from typing import Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .feedback import Feedback


class ProgrammingFeedback(Feedback, BaseModel):
    """Feedback on a programming exercise."""
    file_path: Optional[str] = Field(None, examples=["src/pe1/MergeSort.java"])

    # The line values will always be either both None or both an int:
    line_start: Optional[int] = Field(None, description="Start line number, 0-indexed", ge=0, examples=[1])
    line_end: Optional[int] = Field(None, description="End line number, 0-indexed", ge=0, examples=[2])

    @field_validator('line_start')
    def validate_line_start(cls, v: int, info: ValidationInfo):
        if 'line_end' in info.data and v is None and info.data['line_end'] is not None:
            raise ValueError('line_start can only be None if line_end is None.')
        return v

    @field_validator('line_end')
    def validate_line_end(cls, v: int, info: ValidationInfo):
        if 'line_start' in info.data and v is not None and info.data['line_start'] is not None:
            if v < info.data['line_start']:
                raise ValueError('line_end cannot be less than line_start.')
        if v is None:
            # ensure that either both line values are None or both are not None
            return info.data['line_start']
        return v
