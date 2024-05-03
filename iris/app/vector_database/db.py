import logging
import os
import weaviate
from lectureschema import init_lecture_schema
from repository_schema import init_repository_schema
import weaviate.classes as wvc

logger = logging.getLogger(__name__)


class VectorDatabase:
    """
    Class to interact with the Weaviate vector database
    """
    def __init__(self):
        # Connect to the Weaviate Cloud Service until we set up a proper docker for this project
        self.client = weaviate.connect_to_wcs(
            cluster_url=os.getenv(
            ),  # Replace with your WCS URL
            auth_credentials=weaviate.auth.AuthApiKey(
                os.getenv()
            ),  # Replace with your WCS key
        )
        self.repositories = init_repository_schema(self.client)
        self.lectures = init_lecture_schema(self.client)

    def __del__(self):
        self.client.close()

    def delete_collection(self, collection_name):
        """
        Delete a collection from the database
        """
        if self.client.collections.exists(collection_name):
            if self.client.collections.delete(collection_name):
                logger.log(f"Collection {collection_name} deleted")
            else:
                logger.log(f"Collection {collection_name} failed to delete")

    def delete_object(self, collection_name, property_name, object_property):
        """
        Delete an object from the collection inside the databse
        """
        collection = self.client.collections.get(collection_name)
        collection.data.delete_many(
            where=wvc.query.Filter.by_property(property_name).equal(object_property)
        )
