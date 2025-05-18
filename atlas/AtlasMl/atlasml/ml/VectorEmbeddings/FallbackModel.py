from sentence_transformers import SentenceTransformer
from atlasml.clients.weaviate import get_weaviate_client

def generate_embeddings_local(id: str, sentence: str):
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    embeddings = model.encode(sentence)
    return id, embeddings
