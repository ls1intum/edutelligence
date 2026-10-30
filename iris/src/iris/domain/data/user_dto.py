from typing import Optional

from pydantic import BaseModel, Field


class UserDTO(BaseModel):
    id: int
    first_name: Optional[str] = Field(alias="firstName", default=None)
    last_name: Optional[str] = Field(alias="lastName", default=None)
    # Non-Optional: Artemis omits null/empty via @JsonInclude(NON_EMPTY).
    lang_key: str = Field(alias="langKey", default="en")
