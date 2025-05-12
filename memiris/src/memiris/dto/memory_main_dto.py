from typing import List
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryDto(BaseModel):

    id: UUID = Field(description="The unique identifier of the memory object.")
    title: str = Field(description="The title of the memory object. Should be short.")
    content: str = Field(
        description="The content of the memory object. "
        "Contains the aggregated information from the learnings connecting them to a cohesive whole."
    )
    learnings: List[UUID] = Field(
        description="The list of unique identifiers of learning objects that this memory object was created from."
    )
