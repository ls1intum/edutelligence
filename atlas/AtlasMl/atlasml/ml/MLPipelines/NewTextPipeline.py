import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity

class NewTextPipeline:
    """
    NewTextPipeline handles embedding generation for a single text input,  computes its similarity against existing cluster medoids,
    and persists the association in Weaviate.

    Args:
        text (str): The input text to embed and process.
        uuid (str): A unique identifier for the input text.

    Attributes:
        weaviate_client: A Weaviate client instance used to retrieve and store embedding data.
        best_medoid_idx (int): Index of the most similar cluster medoid to the input embedding.
        similarity_scores (numpy.ndarray): Array of cosine similarity scores between the input embedding and each medoid.

    Methods:
        run(text: str, uuid: str) -> numpy.ndarray:
            1. Generates a local embedding for the provided text and UUID.
            2. Retrieves all cluster medoid embeddings from Weaviate.
            3. Computes cosine similarity between the input embedding and each medoid.
            4. Identifies the medoid with the highest similarity score.
            5. Stores the input embedding in the TEXT collection with a reference to the selected medoid.
            6. Returns the array of similarity scores.
    """
    def __init__(self):
        self.weaviate_client = get_weaviate_client()

    def run(self, text: str, uuid: str):
        embedding_id, embedding = generate_embeddings_local(uuid, text)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        similarity_scores = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
        best_medoid_idx = int(np.argmax(similarity_scores))

        properties = { "properties": [{
                    "text": text ,
                    "uuid": uuid ,
                    "competencyID": clusters[best_medoid_idx]["properties"]["id"]
        } ] }
        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)
        return similarity_scores
