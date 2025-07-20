from enum import Enum
from typing import List, Optional
from uuid import UUID


class ConnectionType(str, Enum):
    """
    Enum representing the type of connection between memories.

    RELATED: General relation between memories
    CONTRADICTS: Memories have contradicting information
    SAME_TOPIC: Memories are about the same topic but not duplicates
    DUPLICATE: Memories contain duplicate information
    CREATED_FROM: One memory was created from another. NEVER USE THIS MANUALLY.
    """

    RELATED = "related"
    CONTRADICTS = "contradicts"
    SAME_TOPIC = "same_topic"
    DUPLICATE = "duplicate"
    CREATED_FROM = "created_from"


class MemoryConnection:
    """
    Represents a connection between two or more memories.
    This enables the system to understand relationships between different memories.
    """

    def __init__(
        self,
        uid: Optional[UUID] = None,
        connection_type: ConnectionType = ConnectionType.RELATED,
        memories: List[UUID] | None = None,
        description: str = "",
        context: Optional[dict] = None,
        weight: float = 1.0,
    ):
        """
        Initialize a MemoryConnection object.

        Args:
            uid: Unique identifier for the connection
            connection_type: Type of connection between the memories
            memories: List of memory IDs that are part of this connection
            description: Optional text describing the nature of the connection
            context: Additional structured information about the connection
            weight: Weight score of this connection (0.0 - 1.0)
        """
        self.id = uid
        self.connection_type = connection_type
        self.memories = memories or []
        self.description = description
        self.context = context or {}
        self.weight = weight

    def __repr__(self):
        memory_count = len(self.memories) if self.memories else 0
        return f"MemoryConnection({self.id}, {self.connection_type.name}, {memory_count} memories)"

    def __eq__(self, other):
        if other is None or not isinstance(other, MemoryConnection):
            return False
        return (
            self.id == other.id
            and self.connection_type == other.connection_type
            and self.memories == other.memories
            and self.description == other.description
            and self.context == other.context
            and self.weight == other.weight
        )
