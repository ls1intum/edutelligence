import json
from typing import List

import weaviate
import weaviate.classes as wvc

from app.vector_repository.lecture_schema import init_schema, LectureSlideChunk
from content_service.Retrieval.abstract_retrieval import AbstractRetrieval


class LectureRetrieval(AbstractRetrieval):
    """
    Class for ingesting repositories into a database.
    """

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def retrieve(self, user_message: str, lecture_id: int = None) -> List[str]:
        response = self.collection.query.near_text(
            near_text=user_message,
            filters=(
                wvc.query.Filter.by_property(LectureSlideChunk.LECTURE_ID).equal(
                    lecture_id
                )
                if lecture_id
                else None
            ),
            return_properties=[
                LectureSlideChunk.PAGE_CONTENT,
                LectureSlideChunk.COURSE_NAME,
            ],
            limit=5,
        )
        print(json.dumps(response, indent=2))
        return response

    def get_collection(self, path: str):
        pass
