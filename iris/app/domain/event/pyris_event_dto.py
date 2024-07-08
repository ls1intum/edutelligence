from typing import TypeVar, Generic

from pydantic import Field, BaseModel

T = TypeVar("T")


class PyrisEventDTO(BaseModel, Generic[T]):
    event_type: str = Field(None, alias="eventType")
    event: T = Field(None, alias="event")
