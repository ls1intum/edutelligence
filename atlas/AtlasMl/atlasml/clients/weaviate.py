import weaviate
import requests

from atlasml.config import settings


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

        # Automatically ensure the class exists
        self._ensure_competency_class()

    def _ensure_competency_class(self):
        """Ensure 'Competency' class exists."""
        if not self.client.collections.exists("Competency"):
            self.client.collections.create(
                name="Competency",
                vectorizer_config=weaviate.classes.config.Configure.Vectorizer.none(),
            )
            print("✅ 'Competency' collection created.")
        else:
            print("ℹ️ 'Competency' collection already exists.")

    def is_alive(self):
        """Check if the Weaviate client is alive."""
        try:
            return self.client.is_live()
        except Exception as e:
            print(f"❌ Weaviate connection failed: {e}")
            return False

    def close(self):
        """Close the Weaviate client."""
        self.client.close()

    def add_embeddings(self, id: str, description: str, embeddings: list[float]):
        """Add an embedding with a custom ID and description to the 'Competency' class."""
        print("--- ADDING EMBEDDING TO WEAVIATE ---")
        uuid = self.competency_collection.data.insert(
            properties={
                "text": description,
                "course_id": id
            },

            vector=embeddings
        )

        print("--- EMBEDDING ADDED TO WEAVIATE ---")
        print("UUID: ", uuid)

    def get_embeddings_rest(self, id: str):
        url = f"http://localhost:8080/v1/objects/Competency/{id}?include=vector"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print("❌ Failed:", response.text)
            return None

    def get_embeddings(self, id: str):
        """Get embeddings for a given ID."""
        print("--- GETTING EMBEDDINGS FROM WEAVIATE ---")
        embedding = self.get_embeddings_rest(id)

        print("--- EMBEDDINGS RETRIEVED FROM WEAVIATE ---")

        return embedding
    
    def get_all_embeddings(self):
        """
        Fetch all objects and their vectors from the 'Competency' collection using REST (no gRPC).
        """
        results = []
        
        response = self.competency_collection.iterator(
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
