from typing import Literal, Optional

from pydantic import BaseModel


class VerdictDTO(BaseModel):
    verdict: Optional[Literal["SUSPICIOUS", "UNSUSPICIOUS", "NEXT_QUESTION"]] = None
    reasoning: Optional[str] = None
