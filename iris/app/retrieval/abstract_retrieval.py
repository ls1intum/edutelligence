from abc import ABC, abstractmethod
from typing import List


class AbstractRetrieval(ABC):
    """
    Abstract class for retrieving data from a database.
    """

    @abstractmethod
    def retrieval_pipeline(
        self, path: str, hybrid_factor: float, result_limit: int
    ) -> List[str]:
        """
        Abstract method to retrieve data from the database.
        """
        pass
