import json
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from memiris.domain.memory_connection import ConnectionType


class MemoryConnectionDLO(BaseModel):
    """DLO for representing a connection between memories identified by LLM."""

    connection_type: ConnectionType = Field(
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
        """Get the JSON schema for a list of MemoryConnectionDLO objects."""
        return json.dumps(cls.json_array_type().json_schema(), indent=2)

    @classmethod
    def json_array_type(cls) -> TypeAdapter:
        """Get the type adapter for a list of MemoryConnectionDLO objects."""
        return TypeAdapter(List[MemoryConnectionDLO])
