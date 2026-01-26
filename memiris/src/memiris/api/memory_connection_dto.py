from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from memiris.domain.memory_connection import ConnectionType, MemoryConnection


class MemoryConnectionDTO(BaseModel):
    """
    DTO for a MemoryConnection with connected memories fully populated.
    """

    id: Optional[str]
    connection_type: ConnectionType = Field(alias="connectionType")
    memories: List[str]
    description: str = ""
    context: Dict = {}
    weight: float = 1.0

    @classmethod
    def from_connection(
        cls,
        connection: MemoryConnection,
    ) -> "MemoryConnectionDTO":
        return cls(
            id=str(connection.id) if connection.id else None,
            connectionType=connection.connection_type,  # type: ignore[arg-type]
            memories=[str(id) for id in connection.memories],
            description=connection.description,
            context=connection.context or {},
            weight=connection.weight,
        )
