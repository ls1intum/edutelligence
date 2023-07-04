from typing import Optional, Tuple

from pydantic import BaseModel, Field, validator

from .feedback import Feedback


class ProgrammingFeedback(Feedback, BaseModel):
    """Feedback on a programming exercise."""
    file_path: Optional[str] = Field(None, example="src/pe1/MergeSort.java")

    # The line values will always be either both None or both an int:
    line_start: Optional[int] = Field(None, example=1)
    line_end: Optional[int] = Field(None, example=2)

    @validator('line_start')
    def validate_line_start(cls, v, values, **kwargs):
        if 'line_end' in values and v is None and values['line_end'] is not None:
            raise ValueError('line_start can only be None if line_end is None.')
        return v
    
    @validator('line_end')
    def validate_line_end(cls, v, values, **kwargs):
        if 'line_start' in values and v is not None and values['line_start'] is not None:
            if v < values['line_start']:
                raise ValueError('line_end cannot be less than line_start.')
        if v is None:
            # ensure that the either both line values are None or both are not None
            return values['line_start']
        return v