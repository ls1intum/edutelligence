from typing import Optional
from pydantic import Field, validator

from .feedback import Feedback


class TextFeedback(Feedback):
    """Feedback on a text exercise."""
    index_start: Optional[int] = Field(None, description="The start index of the feedback in the submission text.", example=0)
    index_end: Optional[int] = Field(None, description="The end index of the feedback in the submission text.", example=10)

    @validator('index_start')
    def validate_index_start(cls, v, values, **kwargs):
        if 'index_end' in values and v is None and values['index_end'] is not None:
            raise ValueError('index_start can only be None if index_end is None.')
        return v
    
    @validator('index_end')
    def validate_index_end(cls, v, values, **kwargs):
        if 'index_start' in values and v is not None and values['index_start'] is not None:
            if v < values['index_start']:
                raise ValueError('index_end cannot be less than index_start.')
        if v is None:
            # ensure that the either both index values are None or both are not None
            return values['index_start']
        return v