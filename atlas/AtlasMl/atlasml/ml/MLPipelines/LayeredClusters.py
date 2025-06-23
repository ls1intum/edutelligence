import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from sklearn.cluster import KMeans, AgglomerativeClustering


class LayeredClusters:
    def __init__(self):
        self.weaviate_client = get_weaviate_client()

    def layered_clustering(self, eps: float = 0.1, min_samples: int = 1, min_cluster_size: int = 1):
        texts = self.weaviate_client.get_all_embeddings(CollectionNames.TEXT.value)
        embeddings = np.vstack([text["vector"] for text in texts])

        labels_hdbscan, centroids, medoids = apply_hdbscan(
            embeddings,
            eps=eps,
            min_samples=min_samples,
            metric=SimilarityMetric.cosine.value,
            min_cluster_size=min_cluster_size
        )
        n_clusters = len(medoids)

        kmeans = KMeans(n_clusters=n_clusters, n_init='auto')
        labels_kmeans = kmeans.fit_predict(embeddings)

        agglomerative = AgglomerativeClustering(n_clusters=n_clusters)
        labels_agglomerative = agglomerative.fit_predict(embeddings)

        return {
            'hdbscan': labels_hdbscan,
            'kmeans': labels_kmeans,
            'agglomerative': labels_agglomerative,
        }
