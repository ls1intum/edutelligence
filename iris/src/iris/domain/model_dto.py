from typing import Optional

from pydantic import BaseModel


class PyrisModelDTO(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
