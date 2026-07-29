from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PyrisEventDTO(BaseModel, Generic[T]):
    event_type: Optional[str] = Field(default=None, alias="eventType")
    event: Optional[T] = Field(default=None, alias="event")
