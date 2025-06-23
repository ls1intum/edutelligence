from sentence_transformers import SentenceTransformer

from atlasml.clients.weaviate import get_weaviate_client


def generate_embeddings(id: str, sentence: str):
    weaviate_client = get_weaviate_client()

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = model.encode(sentence)

    uuid = weaviate_client.add_embeddings(id, sentence, embeddings)
    return uuid, embeddings
