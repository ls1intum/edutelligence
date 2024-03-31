from abc import ABC
from typing import List

import weaviate
import weaviate.classes as wvc

from app.vector_database.lectureschema import init_lecture_schema, LectureSchema
from ..Retrieval.abstract_retrieval import AbstractRetrieval


class LectureRetrieval(AbstractRetrieval, ABC):
    """
    Class for retrieving lecture data from the database.
    """

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_lecture_schema(client)

    def retrieve(
        self,
        user_message: str,
        hybrid_factor: float,
        lecture_id: int = None,
        embedding_vector: [float] = None,
    ) -> List[dict]:
        response = self.collection.query.hybrid(
            query=user_message,
            limit=3,
            filters=(
                wvc.query.Filter.by_property(LectureSchema.LECTURE_ID).equal(lecture_id)
                if lecture_id
                else None
            ),
            alpha=hybrid_factor,
            vector=embedding_vector,
        )
        relevant_chunks = [obj.properties for obj in response.objects]
        return relevant_chunks
