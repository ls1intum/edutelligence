from typing import Optional

from pydantic import BaseModel, Field


class VerdictDTO(BaseModel):
    verdict: Optional[str] = Field(alias="verdict", default=None)
    reasoning: Optional[str] = Field(alias="reasoning", default=None)
