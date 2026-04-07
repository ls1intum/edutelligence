import atexit
import threading

import weaviate
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.config import settings

from .faq_schema import init_faq_schema
from .lecture_transcription_schema import init_lecture_transcription_schema
from .lecture_unit_page_chunk_schema import init_lecture_unit_page_chunk_schema
from .lecture_unit_schema import init_lecture_unit_schema
from .lecture_unit_segment_schema import init_lecture_unit_segment_schema

logger = get_logger(__name__)
batch_update_lock = threading.Lock()


class VectorDatabase:
    """
    Class to interact with the Weaviate vector database
    """

    _lock = threading.Lock()
    static_client_instance = None

    def __init__(self):
        with VectorDatabase._lock:
            if not VectorDatabase.static_client_instance:
                VectorDatabase.static_client_instance = weaviate.connect_to_local(
                    host=settings.weaviate.host,
                    port=settings.weaviate.port,
                    grpc_port=settings.weaviate.grpc_port,
                )
                atexit.register(VectorDatabase.static_client_instance.close)
                logger.info("Weaviate client initialized")
        self.client = VectorDatabase.static_client_instance
        self.lectures = init_lecture_unit_page_chunk_schema(self.client)
        self.transcriptions = init_lecture_transcription_schema(self.client)
        self.lecture_segments = init_lecture_unit_segment_schema(self.client)
        self.lecture_units = init_lecture_unit_schema(self.client)
        self.faqs = init_faq_schema(self.client)

    def delete_collection(self, collection_name):
        """
        Delete a collection from the database
        """
        if self.client.collections.delete(collection_name):
            logger.info("Collection %s deleted", collection_name)
        else:
            logger.error("Collection %s failed to delete", collection_name)

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
