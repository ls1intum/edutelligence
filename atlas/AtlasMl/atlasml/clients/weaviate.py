import weaviate
from atlasml.config import settings

class WeaviateClient:
    def __init__(self, host: str = settings.WEAVIATE_HOST):
        self.client = weaviate.connect_to_local(host=host)

    def _ensure_competency_class(self):
        """Ensure 'Competency' class exists in schema."""
        competency_class = {
            "class": "Competency",
            "description": "A collection of competency texts and their embeddings",
            "properties": [
                {
                    "name": "text",
                    "dataType": ["text"]
                }
            ],
            "vectorIndexType": "hnsw"
        }

        if not self.client.schema.contains({"class": "Competency"}):
            self.client.schema.create_class(competency_class)
            print("✅ 'Competency' class created.")
        else:
            print("ℹ️ 'Competency' class already exists.")

    def is_alive(self):
        """Check if the Weaviate client is alive."""
        try:
            self.client.is_live()
            return True
        except Exception as e:
            print(f"❌ Weaviate connection failed: {e}")
            return False
        
    def close(self):
        """Close the Weaviate client."""
        self.client.close()
        

weaviate_client = WeaviateClient()