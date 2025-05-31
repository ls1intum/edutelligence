from enum import Enum
from typing import List, Optional
from uuid import UUID


class ConnectionType(Enum):
    """
    Enum representing the type of connection between memories.

    RELATED: General relation between memories
    ELABORATES: One memory expands on another memory
    CONTRADICTS: Memories have contradicting information
    PRECEDES: One memory comes before another chronologically
    FOLLOWS: One memory comes after another chronologically
    CAUSES: One memory describes something that causes another
    EXAMPLE_OF: One memory gives an example of the other
    SAME_TOPIC: Memories are about the same topic but not duplicates
    """

    RELATED = "related"
    ELABORATES = "elaborates"
    CONTRADICTS = "contradicts"
    PRECEDES = "precedes"
    FOLLOWS = "follows"
    CAUSES = "causes"
    EXAMPLE_OF = "example_of"
    SAME_TOPIC = "same_topic"


class MemoryConnection:
    """
    Represents a connection between two or more memories.
    This enables the system to understand relationships between different memories.
    """

    def __init__(
        self,
        uid: Optional[UUID] = None,
        connection_type: ConnectionType = ConnectionType.RELATED,
        memories: List[UUID] = None,
        description: str = "",
        context: Optional[dict] = None,
        confidence: float = 1.0,
    ):
        """
        Initialize a MemoryConnection object.

        Args:
            uid: Unique identifier for the connection
            connection_type: Type of connection between the memories
            memories: List of memory IDs that are part of this connection
            description: Optional text describing the nature of the connection
            context: Additional structured information about the connection
            confidence: Confidence score of this connection (0.0 - 1.0)
        """
        self.id = uid
        self.connection_type = connection_type
        self.memories = memories or []
        self.description = description
        self.context = context or {}
        self.confidence = confidence

    def __repr__(self):
        memory_count = len(self.memories) if self.memories else 0
        return f"MemoryConnection({self.id}, {self.connection_type.name}, {memory_count} memories)"
