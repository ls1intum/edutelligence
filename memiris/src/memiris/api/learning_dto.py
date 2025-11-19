from typing import List, Optional

from pydantic import BaseModel

from memiris.domain.learning import Learning


class LearningDTO(BaseModel):
    """
    DTO representing a Learning without vectors.
    """

    id: Optional[str]
    title: str
    content: str
    reference: str
    memories: List[str]

    @classmethod
    def from_learning(cls, learning: Learning) -> "LearningDTO":
        return cls(
            id=str(learning.id) if learning.id else None,
            title=learning.title,
            content=learning.content,
            reference=learning.reference,
            memories=[str(mid) for mid in learning.memories],
        )
