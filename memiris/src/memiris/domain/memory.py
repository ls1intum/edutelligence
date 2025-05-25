from typing import Dict, List, Optional, Sequence
from uuid import UUID


class Memory:
    """
    A memory object represents a processed learning object.
    It only contains relevant information to be remembered later.
    If more details are needed, the learning object can be referenced.
    """

    id: Optional[UUID]  # The unique identifier of the memory object.
    title: str  # The title of the memory object. Used for identification by the user.
    content: str  # The content of the memory object. Contains the information that was learned without details.
    learnings: List[
        UUID
    ]  # The learning object(s) that this memory object was created from.
    vectors: Dict[
        str, Sequence[float]
    ]  # The vector representations of the memory object,
    slept_on: bool = False  # Whether the memory has been slept on or not.
    deleted: bool = False  # Whether the memory has been marked as deleted.

    def __init__(
        self,
        title: str,
        content: str,
        learnings: List[UUID],
        uid: Optional[UUID] = None,
        vectors: Optional[Dict[str, Sequence[float]]] = None,
        slept_on: bool = False,
        deleted: bool = False,
    ) -> None:
        if vectors is None:
            vectors = {}
        self.id = uid
        self.title = title
        self.content = content
        self.learnings = learnings
        self.vectors = vectors
        self.slept_on = slept_on
        self.deleted = deleted

    def __str__(self) -> str:
        return f"{self.title}: {self.content} ({self.learnings})"

    def __repr__(self) -> str:
        return f"Memory({self.id}, {self.title}, {self.content}, {repr(self.learnings)}, {repr(self.vectors)})"

    def __eq__(self, other) -> bool:
        return (
            self.title == other.title
            and self.content == other.content
            and self.learnings == other.learnings
        )
