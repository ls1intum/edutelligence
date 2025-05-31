from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryConnectionDto(BaseModel):
    """DTO for representing a connection between memories identified by LLM."""

    connection_type: str = Field(
        ...,
        description="Type of connection between the memories. Only use the defined values",
    )
    memories: List[UUID] = Field(
        ..., description="List of memory IDs that are part of this connection"
    )
    description: str = Field(
        ...,
        description="A description explaining the nature of the connection in detail",
    )
    weight: Optional[float] = Field(
        default=0.5,
        description="Weight score for this connection, between 0.0 and 1.0",
        ge=0.0,
        le=1.0,
    )

    @classmethod
    def json_array_schema(cls) -> str:
        """Get the JSON schema for a list of MemoryConnectionDto objects."""
        return str(cls.model_json_schema())

    @classmethod
    def json_array_type(cls):
        """Get the type adapter for a list of MemoryConnectionDto objects."""
        return TypeAdapter(List[MemoryConnectionDto])
