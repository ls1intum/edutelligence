from typing import TypeVar, Generic, Optional

from pydantic import Field, BaseModel

T = TypeVar("T")


class PyrisEventDTO(BaseModel, Generic[T]):
    event_type: Optional[str] = Field(default=None, alias="eventType")
    event: Optional[T] = Field(default=None, alias="event")
