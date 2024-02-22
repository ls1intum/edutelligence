from abc import ABC, abstractmethod
from typing import List, Dict


class AbstractIngestion(ABC):
    """
    Abstract class for ingesting repositories into a database.
    """

    @abstractmethod
    def chunk_files(self, path: str) -> List[Dict[str, str]]:
        """
        Abstract method to chunk code files in the root directory.
        """
        pass

    @abstractmethod
    def ingest(self, path: str) -> bool:
        """
        Abstract method to ingest repositories into the database.
        """
        pass

    @abstractmethod
    def update(self, path: str):
        """
        Abstract method to update a repository in the database.
        """
        pass
