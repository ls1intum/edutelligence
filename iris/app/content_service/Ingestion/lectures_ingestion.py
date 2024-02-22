from typing import List, Dict
import weaviate

from app.vector_repository.lecture_schema import init_schema
from content_service.Ingestion.abstract_ingestion import AbstractIngestion


class LectureIngestion(AbstractIngestion):  # Inherits from the abstract class

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def chunk_files(self, path: str):
        # Implement chunking logic here or raise NotImplementedError if not applicable
        pass
    def ingest(self, lecture_path)-> bool:
        """
        Ingest the lectures into the weaviate database
        """
        # Implement ingestion logic here
        pass

    def update(self, lecture: Dict[str, str]):
        """
        Update a lecture in the weaviate database
        """
        # Implement update logic here or raise NotImplementedError if not applicable
        pass