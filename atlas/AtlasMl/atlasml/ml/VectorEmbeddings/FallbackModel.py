from sentence_transformers import SentenceTransformer
from atlasml.clients.weaviate import weaviate_client

def generate_embeddings(id: str, sentence: str):
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    embeddings = model.encode(sentence)

    uuid = weaviate_client.add_embeddings(id, sentence, embeddings)
    return uuid, embeddings 
