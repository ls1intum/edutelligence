from enum import Enum
from typing import List, Optional
from uuid import UUID


class ConnectionType(str, Enum):
    """
    Enum representing the type of connection between memories.

    CONTRADICTS: Use when memories make incompatible factual claims that cannot both be true in the same \
        context/time (for example, opposite preferences or conflicting personal facts).
    DUPLICATE: Highest-priority overlap class. Use for exact duplicates, partial duplicates, \
        near-duplicates, or same-topic memories whose information can be meaningfully merged/deduplicated.
    SAME_TOPIC: Use when memories are about the same specific topic/entity but should remain separate because \
        each contributes distinct, non-redundant information that is not sensibly deduplicated.
    RELATED: Lowest-priority fallback for distinct memories with a useful contextual relationship (same \
        broader situation/theme) when they are not contradictions, not deduplicable overlap, and not a \
        SAME_TOPIC case.
    CREATED_FROM: Lineage link indicating one memory was derived/generated from another memory during \
        system processing. NEVER USE THIS MANUALLY.
    """

    CONTRADICTS = "contradicts"
    DUPLICATE = "duplicate"
    SAME_TOPIC = "same_topic"
    RELATED = "related"
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
