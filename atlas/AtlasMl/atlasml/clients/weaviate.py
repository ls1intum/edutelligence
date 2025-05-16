import weaviate
import requests
import logging
from enum import Enum

from atlasml.config import settings

# Define enum for Collection names  

class CollectionNames(str, Enum):
    COMPETENCY = "Competency"
    CLUSTER = "Cluster"
    COURSE = "Course"


logger = logging.getLogger(__name__)

class WeaviateClient:
    def __init__(
        self,
        host: str = settings.WEAVIATE_HOST,
        port: int = settings.WEAVIATE_PORT,
        grpc_port: int = settings.WEAVIATE_GRPC_PORT,
    ):
        self.client = weaviate.connect_to_local(
            host=host,
            port=port,
            grpc_port=grpc_port,
        )

        self.competency_collection = self.client.collections.get("Competency")

        self._ensure_collections_exist()

    def _ensure_collections_exist(self):
        """Ensure 'Competency' class exists."""
        for collection in CollectionNames:
            if not self.client.collections.exists(collection):
                self.client.collections.create(
                    name=collection,
                    vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
                )
                logger.info(f"✅ {collection} collection created.")
        
        logger.info("--- All collections initialized ---")

    def _check_if_collection_exists(self, collection_name: str):
        """Check if the collection exists."""
        if collection_name not in [c.value for c in CollectionNames]:
            logger.error(f"❌ Invalid collection name: {collection_name}")
            raise ValueError(f"Collection name '{collection_name}' is not valid. Use one of: {', '.join([c.value for c in CollectionNames])}")
        
        return self.client.collections.exists(collection_name)
        

    def is_alive(self):
        """Check if the Weaviate client is alive."""
        try:
            return self.client.is_live()
        except Exception as e:
            logger.error(f"❌ Weaviate connection failed: {e}")
            return False

    def close(self):
        """Close the Weaviate client."""
        self.client.close()

    def add_embeddings(self, collection_name: str, id: str, description: str, embeddings: list[float]):
        """Add an embedding with a custom ID and description to the specified collection."""
        logger.info(f"--- ADDING EMBEDDING TO WEAVIATE COLLECTION '{collection_name}' ---")
        self._check_if_collection_exists(collection_name)
        collection = self.client.collections.get(collection_name)
        uuid = collection.data.insert(
            properties={
                "text": description,
                "course_id": id
            },
            vector=embeddings
        )

        logger.info("--- EMBEDDING ADDED TO WEAVIATE ---")
        logger.info(f"UUID: {uuid}")

    def get_embeddings_rest(self, collection_name: str, id: str):
        """Get embeddings for a given ID from the specified collection using REST (no gRPC)."""
        self._check_if_collection_exists(collection_name)

        url = f"http://localhost:8080/v1/objects/{collection_name}/{id}?include=vector"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"❌ Failed: {response.text}")
            return None

    def get_embeddings(self, collection_name: str, id: str):
        """Get embeddings for a given ID from the specified collection."""
        logger.info(f"--- GETTING EMBEDDINGS FROM WEAVIATE COLLECTION '{collection_name}' ---")
        self._check_if_collection_exists(collection_name)

        embedding = self.get_embeddings_rest(collection_name, id)

        logger.info("--- EMBEDDINGS RETRIEVED FROM WEAVIATE ---")

        return embedding
    
    def get_all_embeddings(self, collection_name: str = "Competency"):
        """
        Fetch all objects and their vectors from the specified collection using REST (no gRPC).
        
        Args:
            collection_name: Name of the collection to fetch embeddings from. Defaults to 'Competency'.
            
        Returns:
            List of dictionaries containing id, text, and vector for each object.
        """
        self._check_if_collection_exists(collection_name)

        results = []
        collection = self.client.collections.get(collection_name)
        response = collection.iterator(
            include_vector=True,
        )

        for obj in response:
            results.append({
                "id": obj.uuid,
                "text": obj.properties.get("text"),
                "vector": obj.vector
            })

        return results

_weaviate_client_instance = None

def get_weaviate_client() -> WeaviateClient:
    """Get a Weaviate client instance using singleton pattern."""
    global _weaviate_client_instance
    if _weaviate_client_instance is None:
        _weaviate_client_instance = WeaviateClient()
    return _weaviate_client_instance
