from conftest import TEST_WEAVIATE_HOST, TEST_WEAVIATE_PORT, TEST_WEAVIATE_GRPC_PORT

import atexit
import weaviate
from weaviate.classes.query import Filter

from iris.vector_database.faq_schema import init_faq_schema
from iris.vector_database.lecture_transcription_schema import init_lecture_transcription_schema
from iris.vector_database.lecture_unit_page_chunk_schema import init_lecture_unit_page_chunk_schema
from iris.vector_database.lecture_unit_schema import init_lecture_unit_schema
from iris.vector_database.lecture_unit_segment_schema import init_lecture_unit_segment_schema


# - Version of VectorDatabase class which resets on every run
# - used in code via monkey patch
class TestVectorDatabase:
    def __init__(self):
        with TestVectorDatabase._lock:
            TestVectorDatabase._client_instance = weaviate.connect_to_local(
                host=TEST_WEAVIATE_HOST,
                port=TEST_WEAVIATE_PORT,
                grpc_port=TEST_WEAVIATE_GRPC_PORT,
            )
            atexit.register(TestVectorDatabase._client_instance.close)

        self.client = TestVectorDatabase._client_instance
        self.lectures = init_lecture_unit_page_chunk_schema(self.client)
        self.transcriptions = init_lecture_transcription_schema(self.client)
        self.lecture_segments = init_lecture_unit_segment_schema(self.client)
        self.lecture_units = init_lecture_unit_schema(self.client)
        self.faqs = init_faq_schema(self.client)

    def delete_collection(self, collection_name):
        """
        Delete a collection from the database
        """
        self.client.collections.delete(collection_name)

    def delete_object(self, collection_name, property_name, object_property):
        """
        Delete an object from the collection inside the database
        """
        collection = self.client.collections.get(collection_name)
        collection.data.delete_many(
            where=Filter.by_property(property_name).equal(object_property)
        )

    def get_client(self):
        """
        Get the Weaviate client
        """
        return self.client
