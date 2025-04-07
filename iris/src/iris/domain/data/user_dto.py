from typing import Optional

from pydantic import BaseModel, Field


class UserDTO(BaseModel):
    id: int
    first_name: Optional[str] = Field(alias="firstName", default=None)
    last_name: Optional[str] = Field(alias="lastName", default=None)
