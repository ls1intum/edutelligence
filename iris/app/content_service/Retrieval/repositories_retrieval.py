import json
from typing import List

from vector_repository.repository_schema import RepositoryChunk

from content_service.Retrieval.abstract_retrieval import AbstractRetrieval

import weaviate.classes as wvc


class RepositoryRetrieval(AbstractRetrieval):
    """
    Class for Retrieving vector_repository for from the database.
    """

    def retrieve(self, user_message: str, repository_id: int = None) -> List[str]:
        response = self.collection.query.near_text(
            near_text=user_message,
            filters=(
                wvc.query.Filter.by_property(RepositoryChunk.LECTURE_ID).equal(
                    repository_id
                )
                if repository_id
                else None
            ),
            return_properties=[
                RepositoryChunk.REPOSITORY_NAME,
                RepositoryChunk.REPOSITORY_DESCRIPTION,
            ],
            limit=5,
        )
        print(json.dumps(response, indent=2))
        return response

    def get_collection(self, path: str):
        pass
