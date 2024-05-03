from abc import ABC
from typing import List

import weaviate
import weaviate.classes as wvc

from app.content_service.Retrieval.abstract_retrieval import AbstractRetrieval
from app.vector_database.lectureschema import init_lecture_schema, LectureSchema


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
        message_vector: [float] = None,
    ) -> List[str]:
        response = self.collection.query.hybrid(
            query=user_message,
            filters=(
                wvc.query.Filter.by_property(LectureSchema.LECTURE_ID).equal(lecture_id)
                if lecture_id
                else None
            ),
            alpha=hybrid_factor,
            vector=message_vector,
            return_properties=[
                LectureSchema.PAGE_TEXT_CONTENT,
                LectureSchema.PAGE_IMAGE_DESCRIPTION,
                LectureSchema.COURSE_NAME,
            ],
            limit=5,
        )
        return response
