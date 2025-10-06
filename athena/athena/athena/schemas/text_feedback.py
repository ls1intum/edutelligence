from typing import Optional
from pydantic import Field, ValidationInfo, field_validator

from .feedback import Feedback


class TextFeedback(Feedback):
    """Feedback on a text exercise."""
    index_start: Optional[int] = Field(None, description="The start index of the feedback in the submission text.", examples=[0])
    index_end: Optional[int] = Field(None, description="The end index of the feedback in the submission text.", examples=[10])

    @field_validator('index_start')
    def validate_index_start(cls, v: int, info: ValidationInfo):
        if 'index_end' in info.data and v is None and info.data['index_end'] is not None:
            raise ValueError('index_start can only be None if index_end is None.')
        return v

    @field_validator('index_end')
    def validate_index_end(cls, v: int, info: ValidationInfo):
        if 'index_start' in info.data and v is not None and info.data['index_start'] is not None:
            if v < info.data['index_start']:
                raise ValueError('index_end cannot be less than index_start.')
        if v is None:
            # ensure that the either both index values are None or both are not None
            return info.data['index_start']
        return v
