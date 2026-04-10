import atexit
import threading

import weaviate
from weaviate.classes.init import Auth
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
    _static_collections: dict = {}

    def __init__(self):
        with VectorDatabase._lock:
            if not VectorDatabase.static_client_instance:
                auth = (
                    Auth.api_key(settings.weaviate.api_key)
                    if settings.weaviate.api_key
                    else None
                )
                VectorDatabase.static_client_instance = weaviate.connect_to_custom(
                    http_host=settings.weaviate.host,
                    http_port=settings.weaviate.port,
                    http_secure=settings.weaviate.http_secure,
                    grpc_host=settings.weaviate.host,
                    grpc_port=settings.weaviate.grpc_port,
                    grpc_secure=settings.weaviate.grpc_secure,
                    auth_credentials=auth,
                )
                atexit.register(VectorDatabase.static_client_instance.close)
                logger.info("Weaviate client initialized")

                # Initialize schemas exactly once per process. Running them on
                # every ``VectorDatabase()`` call is racy: multiple threads can
                # pass the ``exists()`` check and then all call ``create()``,
                # with the losers getting a 422 "class already exists".
                client = VectorDatabase.static_client_instance
                VectorDatabase._static_collections = {
                    "lectures": init_lecture_unit_page_chunk_schema(client),
                    "transcriptions": init_lecture_transcription_schema(client),
                    "lecture_segments": init_lecture_unit_segment_schema(client),
                    "lecture_units": init_lecture_unit_schema(client),
                    "faqs": init_faq_schema(client),
                }

        self.client = VectorDatabase.static_client_instance
        collections = VectorDatabase._static_collections
        self.lectures = collections["lectures"]
        self.transcriptions = collections["transcriptions"]
        self.lecture_segments = collections["lecture_segments"]
        self.lecture_units = collections["lecture_units"]
        self.faqs = collections["faqs"]

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
