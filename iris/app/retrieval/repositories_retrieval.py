from typing import List

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from app.retrieval.abstract_retrieval import AbstractRetrieval
from app.vector_database.repository_schema import (
    init_repository_schema,
    RepositorySchema,
)


class RepositoryRetrieval(AbstractRetrieval):
    """
    Class for Retrieving repository code for from the vector database.
    """

    def __init__(self, client: WeaviateClient):
        self.collection = init_repository_schema(client)

    def retrieval_pipeline(
        self,
        user_message: str,
        result_limit: int,
        repository_id: int = None,
    ) -> List[str]:
        """
        Retrieve repository code from the database.
        """
        response = self.collection.query.near_text(
            near_text=user_message,
            filters=(
                Filter.by_property(RepositorySchema.REPOSITORY_ID.value).equal(
                    repository_id
                )
                if repository_id
                else None
            ),
            return_properties=[
                RepositorySchema.REPOSITORY_ID.value,
                RepositorySchema.COURSE_ID.value,
                RepositorySchema.CONTENT.value,
                RepositorySchema.EXERCISE_ID.value,
                RepositorySchema.FILEPATH.value,
            ],
            limit=result_limit,
        )
        return response
