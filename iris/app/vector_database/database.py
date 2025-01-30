import logging
import weaviate

from .faq_schema import init_faq_schema
from .lecture_schema import init_lecture_schema
from weaviate.classes.query import Filter
from app.config import settings
import threading

logger = logging.getLogger(__name__)


class VectorDatabase:
    """
    Class to interact with the Weaviate vector database
    """

    _lock = threading.Lock()
    _client_instance = None

    def __init__(self):
        with VectorDatabase._lock:
            if not VectorDatabase._client_instance:
                VectorDatabase._client_instance = weaviate.connect_to_local(
                    host=settings.weaviate.host,
                    port=settings.weaviate.port,
                    grpc_port=settings.weaviate.grpc_port,
                )
                logger.info("Weaviate client initialized")
        self.client = VectorDatabase._client_instance
        self.lectures = init_lecture_schema(self.client)
        self.faqs = init_faq_schema(self.client)

    def delete_collection(self, collection_name):
        """
        Delete a collection from the database
        """
        if self.client.collections.exists(collection_name):
            if self.client.collections.delete(collection_name):
                logger.info(f"Collection {collection_name} deleted")
            else:
                logger.error(f"Collection {collection_name} failed to delete")

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
