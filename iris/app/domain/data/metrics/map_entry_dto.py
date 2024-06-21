from typing import Optional
from pydantic import BaseModel


class MapEntryDTO(BaseModel):
    key: Optional[int] = None
    value: Optional[int] = None
