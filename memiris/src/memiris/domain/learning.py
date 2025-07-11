from typing import Dict, List, Optional, Sequence
from uuid import UUID


class Learning:
    """
    A learning object represents a piece of information that has been learned from a source.
    """

    id: Optional[UUID]
    title: str  # The title of the learning object
    content: str  # The content of the learning object. Contains the information that was learned and details about it.
    reference: str  # The reference to the source this learning object was learned from
    memories: List[
        UUID
    ]  # The memory object(s) that were created from this learning object
    vectors: Dict[str, Sequence[float]] = {}  # The vectors of the learning object

    def __init__(
        self,
        title: str,
        content: str,
        reference: str,
        memories: Optional[List[UUID]] = None,
        uid: Optional[UUID] = None,
        vectors: Optional[Dict[str, Sequence[float]]] = None,
    ):
        self.id = uid
        self.title = title
        self.content = content
        self.reference = reference
        self.memories = memories if memories is not None else []
        self.vectors = vectors if vectors is not None else {}

    def __str__(self):
        return f"{self.title}: {self.content} ({self.reference})"

    def __repr__(self):
        return f"Learning({self.title}, {self.content}, {self.reference})"

    def __eq__(self, other):
        if self.id:
            return self.id == other.id
        else:
            return (
                self.title == other.title
                and self.content == other.content
                and self.reference == other.reference
            )
