from sentence_transformers import SentenceTransformer
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

def generate_embeddings(uuid: str, sentence: str):
    weaviate_client = get_weaviate_client()

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = model.encode(sentence)
    if hasattr(embeddings, 'detach'):
        embeddings = embeddings.detach().cpu().numpy().tolist()
    elif hasattr(embeddings, 'tolist'):
        embeddings = embeddings.tolist()

    properties = {"properties": [{
        "text_id": "",
        "text": sentence,
        "competency_ids": ""
    }]}

    uuid = weaviate_client.add_embeddings(CollectionNames.TEXT.value, embeddings, properties)
    return uuid, embeddings


def generate_embeddings_local(uuid: str, sentence: str):
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = model.encode(sentence)
    if hasattr(embeddings, 'detach'):
        embeddings = embeddings.detach().cpu().numpy().tolist()
    elif hasattr(embeddings, 'tolist'):
        embeddings = embeddings.tolist()
    return uuid, embeddings