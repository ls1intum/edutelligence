import os
from typing import List, Tuple, Optional, Union
from dotenv import load_dotenv
from enum import Enum

from openai import AzureOpenAI, OpenAIError
from sentence_transformers import SentenceTransformer

from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

load_dotenv()


class ModelDimension(Enum):
    """Enum for embedding model dimensions."""
    TEXT_EMBEDDING_THREE_SMALL = 1536
    TEXT_EMBEDDING_THREE_LARGE = 3072
    ALL_MINILM_L6_V2 = 384


class EmbeddingGenerator:
    """Handles generation of text embeddings using different models."""
    
    def __init__(self):
        self._local_model = None
        self._azure_client = None
    
    @property
    def local_model(self) -> SentenceTransformer:
        """Lazy-load the local SentenceTransformer model."""
        if self._local_model is None:
            self._local_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return self._local_model
    
    @property
    def azure_client(self) -> AzureOpenAI:
        """Lazy-load the Azure OpenAI client."""
        if self._azure_client is None:
            self._azure_client = AzureOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                azure_endpoint=os.environ.get("OPENAI_API_URL"),
                api_version="2023-05-15",
            )
        return self._azure_client
    
    def generate_embeddings_openai(self, description: str) -> List[float]:
        """
        Generate embeddings using Azure OpenAI service.
        
        Args:
            description: Text to generate embeddings for.
            
        Returns:
            List of embedding values.
            
        Raises:
            OpenAIError: If the API request fails.
        """
        try:
            response = self.azure_client.embeddings.create(
                model="te-3-small",
                input=description,
            )
            return response.data[0].embedding
        except OpenAIError as e:
            raise OpenAIError(f"Failed to generate OpenAI embeddings: {e}")
    
    def generate_embeddings_local(self, sentence: str) -> List[float]:
        """
        Generate embeddings using local SentenceTransformer model.
        
        Args:
            sentence: Text to generate embeddings for.
            
        Returns:
            List of embedding values.
        """
        embeddings = self.local_model.encode(sentence)
        return self._convert_to_list(embeddings)
    
    def generate_embeddings_with_storage(
        self, 
        uuid: str, 
        sentence: str
    ) -> Tuple[str, List[float]]:
        """
        Generate embeddings and store them in Weaviate.
        
        Args:
            uuid: Unique identifier for the text.
            sentence: Text to generate embeddings for.
            
        Returns:
            Tuple of (uuid, embeddings).
        """
        weaviate_client = get_weaviate_client()
        
        embeddings = self.generate_embeddings_local(sentence)
        
        properties = {
            "properties": [{
                "text_id": "",
                "text": sentence,
                "competency_ids": ""
            }]
        }
        
        stored_uuid = weaviate_client.add_embeddings(
            CollectionNames.TEXT.value, 
            embeddings, 
            properties
        )
        return stored_uuid, embeddings
    
    @staticmethod
    def _convert_to_list(embeddings) -> List[float]:
        """Convert various embedding formats to list."""
        if hasattr(embeddings, 'detach'):
            return embeddings.detach().cpu().numpy().tolist()
        elif hasattr(embeddings, 'tolist'):
            return embeddings.tolist()
        return list(embeddings)


# Global instance for backward compatibility
_generator = EmbeddingGenerator()

# Backward compatibility functions
def generate_embeddings_openai(description: str) -> List[float]:
    """Generate embeddings using Azure OpenAI service."""
    return _generator.generate_embeddings_openai(description)


def generate_embeddings_local(sentence: str) -> List[float]:
    """Generate embeddings using local SentenceTransformer model."""
    return _generator.generate_embeddings_local(sentence)


def generate_embeddings(uuid: str, sentence: str) -> Tuple[str, List[float]]:
    """Generate embeddings and store them in Weaviate."""
    return _generator.generate_embeddings_with_storage(uuid, sentence)