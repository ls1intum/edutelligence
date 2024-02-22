from abc import ABC, abstractmethod
from typing import List, Dict


class AbstractRetrieval(ABC):
    """
    Abstract class for ingesting repositories into a database.
    """

    @abstractmethod
    def retrieve(self, path: str) -> List[str]:
        """
        Abstract method to ingest repositories into the database.
        """
        pass

    @abstractmethod
    def get_collection(self, path: str):
        """
        Abstract method to update a repository in the database.
        """
        pass
