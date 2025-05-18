import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity

class PeriodicPipeline:
    """
    InitialPipeline orchestrates loading texts from Artemis, generating embeddings, clustering them via HDBSCAN,
     and computing a similarity matrix of cluster medoids.

    Args:
        texts: Fetch and feed texts from Artemis.
    """
    def __init__(self):
        self.weaviate_client = get_weaviate_client()
        self.texts = None

    def run(self, eps: float = 0.1, min_samples: int = 5, min_cluster_size: int = 5):
        self.texts = self.weaviate_client.get_all_embeddings(CollectionNames.TEXT.value)

        # Generate embeddings for each text entry and collect UUIDs
        embeddings_list = []
        embeddings_uuids = []
        for textEntry in self.texts["properties"]:
            emb_id, emb = generate_embeddings_local(textEntry["id"], textEntry["text"])
            embeddings_list.append(emb)
            embeddings_uuids.append(emb_id)

        embeddings = np.vstack(embeddings_list)
        embeddings_uuids = np.array(embeddings_uuids)

        # Cluster texts and get cluster medoids
        labels, centroids, medoids = apply_hdbscan(
            embeddings,
            eps=eps,
            min_samples=min_samples,
            metric=SimilarityMetric.cosine.value,
            min_cluster_size=min_cluster_size
        )

        # Compute pairwise cosine similarities between medoids
        similarity_matrix = cosine_similarity(medoids)

        # Expose clusters and similarity matrix as instance variables
        for index in range(len(medoids)):
            cluster = { "properties": [{
                "id": "id",
                "name": str(index),
                "size": int((labels == index).sum()),
                "members": embeddings_uuids[labels == index].tolist(),
                }]}
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTER.value, medoids[index].tolist(), cluster)

        # Return the similarity matrix
        return similarity_matrix
