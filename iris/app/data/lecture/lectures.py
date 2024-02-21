import json
import weaviate
import weaviate.classes as wvc

from lecture_schema import init_schema, LectureSlideChunk

class Lectures:

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def ingest(self, lectures):
        pass
    def retrieve(self, user_message: str, lecture_id: int = None):
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
