from abc import ABC, abstractmethod
from typing import List

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory


class MemoryCreator(ABC):
    """
    Abstract base class for creating memories using a large language model.
    """

    @abstractmethod
    def create(self, learnings: List[Learning], tenant: str, **kwargs) -> List[Memory]:
        """
        Create memories from the given learnings.

        Args:
            learnings: A list of Learning objects to create memories from.
            tenant: The tenant identifier for multi-tenant support.
            **kwargs: Additional keyword arguments.

        Returns:
            A list of created Memory objects.
        """
        pass
