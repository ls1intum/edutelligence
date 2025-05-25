from typing import Optional

from memiris.domain.learning import Learning
from memiris.dto.learning_creation_dto import LearningCreationDto
from memiris.dto.learning_main_dto import LearningDto


def creation_dto_to_learning(
    learning_dto: LearningCreationDto, reference: Optional[str]
) -> Learning:
    """
    Convert a LearningCreationDto to a Learning object.
    """
    return Learning(
        title=learning_dto.title,
        content=learning_dto.content,
        reference=reference or "",
    )


def learning_to_creation_dto(learning: Learning) -> LearningCreationDto:
    """
    Convert a Learning object to a LearningCreationDto.
    """
    return LearningCreationDto(title=learning.title, content=learning.content)


def dto_to_learning(learning_dto: LearningDto) -> Learning:
    """
    Convert a LearningDto to a Learning object.
    """
    return Learning(
        uid=learning_dto.id,
        title=learning_dto.title,
        content=learning_dto.content,
        reference="",
    )


def learning_to_dto(learning: Learning) -> LearningDto:
    """
    Convert a Learning object to a LearningDto.
    """
    return LearningDto(
        id=learning.id,  # type: ignore
        title=learning.title,
        content=learning.content,
    )
