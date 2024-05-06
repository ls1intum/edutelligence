from abc import ABC, abstractmethod
from typing import List, Dict


class AbstractIngestion(ABC):
    """
    Abstract class for ingesting repositories into a database.
    """

    @abstractmethod
    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """
        Abstract method to chunk code files in the root directory.
        """
        pass
