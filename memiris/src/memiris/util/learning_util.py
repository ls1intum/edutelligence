from typing import Optional

from memiris.domain.learning import Learning
from memiris.dto.learning_dto import LearningDto


def dto_to_learning(learning_dto: LearningDto, reference: Optional[str]) -> Learning:
    """
    Convert a LearningDto to a Learning object.
    """
    return Learning(
        title=learning_dto.title,
        content=learning_dto.content,
        reference=reference or "",
    )


def learning_to_dto(learning: Learning) -> LearningDto:
    """
    Convert a Learning object to a LearningDto.
    """
    return LearningDto(title=learning.title, content=learning.content)
