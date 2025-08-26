from typing import Optional

from memiris.dlo.learning_creation_dlo import LearningCreationDLO
from memiris.dlo.learning_main_dlo import LearningDLO
from memiris.domain.learning import Learning


def creation_dlo_to_learning(
    learning_dlo: LearningCreationDLO, reference: Optional[str]
) -> Learning:
    """
    Convert a LearningCreationDLO to a Learning object.
    """
    return Learning(
        title=learning_dlo.title,
        content=learning_dlo.content,
        reference=reference or "",
    )


def learning_to_creation_dlo(learning: Learning) -> LearningCreationDLO:
    """
    Convert a Learning object to a LearningCreationDLO.
    """
    return LearningCreationDLO(title=learning.title, content=learning.content)


def dlo_to_learning(learning_dlo: LearningDLO) -> Learning:
    """
    Convert a LearningDLO to a Learning object.
    """
    return Learning(
        uid=learning_dlo.id,
        title=learning_dlo.title,
        content=learning_dlo.content,
        reference="",
    )


def learning_to_dlo(learning: Learning) -> LearningDLO:
    """
    Convert a Learning object to a LearningDLO.
    """
    return LearningDLO(
        id=learning.id,  # type: ignore
        title=learning.title,
        content=learning.content,
    )
