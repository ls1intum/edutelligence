from abc import ABC
from uuid import UUID

from memiris.domain.learning import Learning
from memiris.repository.crud_repository import BaseRepository


class LearningRepository(BaseRepository[Learning, UUID], ABC):
    """
    LearningRepository is an abstract class that defines the database operations for Learning objects.
    """

    pass
