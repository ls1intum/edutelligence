from sentence_transformers import SentenceTransformer

from atlasml.clients.weaviate import get_weaviate_client, CollectionNames


def generate_embeddings(id: str, sentence: str):
    weaviate_client = get_weaviate_client()

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = model.encode(sentence)

    properties = {"properties": [{
        "text_id": "",
        "text": sentence,
        "competency_ids": ""
    }]}

    uuid = weaviate_client.add_embeddings(CollectionNames.TEXT.value, embeddings, )
    return uuid, embeddings
