import pandas as pd
import numpy as np
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity

class InitialPipeline:
    """
    InitialPipeline orchestrates loading texts from Artemis, generating embeddings, clustering them via HDBSCAN,
     and computing a similarity matrix of cluster medoids.

    Args:
        texts (np.ndarray): Fetch and feed 2D array of texts from Artemis.

    Attributes:
        embeddings_uuids (np.ndarray): Array of embedding UUIDs for each text entry.
        embeddings (np.ndarray): 2D array of vector embeddings for all texts.
        labels (list[int]): Cluster labels assigned to each embedding.
        medoids (np.ndarray): Representative vectors (medoids) for each identified cluster.
        similarity_matrix (np.ndarray): Pairwise cosine similarity matrix of the medoids.
    """
    def __init__(self, texts: np.ndarray):
        self.embeddings_uuids = None
        self.embeddings = None
        self.similarity_matrix = None
        self.medoids = None
        self.labels = None
        self.texts = texts

    def run(self, eps: float = 0.1, min_samples: int = 5, min_cluster_size: int = 5):
        # TODO: Get all text data from Artemis
        texts = self.texts

        # TODO: get the uuids from the texts
        # Generate embeddings for each text entry and collect UUIDs
        embeddings_list = []
        embeddings_uuids = []
        for idx, t in enumerate(texts):
            emb_id, emb = generate_embeddings_local(str(idx), t)
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
        # TODO: Save to DB
        self.embeddings = embeddings
        self.embeddings_uuids = embeddings_uuids
        self.labels = labels
        self.medoids = medoids
        self.similarity_matrix = similarity_matrix

        # Return the similarity matrix
        return self.similarity_matrix

