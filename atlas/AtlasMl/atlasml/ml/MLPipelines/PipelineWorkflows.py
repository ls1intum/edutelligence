import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames, WeaviateClient
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity
from atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


class PipelineWorkflows:
    def __init__(self):
        self.weaviate_client = get_weaviate_client()

    """
    ClusterToCompetencyPipeline orchestrates the workflow of assigning new competency texts
    to their closest existing cluster medoids and persisting those relationships in Weaviate.

    Attributes:
        weaviate_client: A Weaviate client instance used to fetch and store embedding data.
        clusters: A list of cluster entries, each containing a medoid embedding fetched from Weaviate.
        competencies: A list of competency entries fetched from Weaviate to be processed.

    Methods:
        run() -> None:
            1. Fetches all cluster medoid embeddings and all competency records from Weaviate.
            2. For each competency, generates a local embedding.
            3. Computes cosine similarity between the competency embedding and each cluster medoid.
            4. Identifies the most similar medoid (highest cosine similarity).
            5. Associates the competency with that cluster by writing the embedding and linkage
               back into the competency collection in Weaviate.
    """
    def clusterToCompetencyPipeline(self):
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)

        for competency in competencies:
            uuid, embedding = generate_embeddings_local(competency["properties"]["uuid"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "competency_id": uuid ,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "clusterID": clusters[best_medoid_idx]["properties"]["uuid"]
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)


    """
    ReclusterPipeline orchestrates loading texts, clustering them, and computing similarity matrices.
    
    This pipeline performs the following steps:
    1. Loads all text embeddings from the database
    2. Retrieves existing cluster centers
    3. Applies HDBSCAN clustering to create new clusters
    4. Computes similarity matrix between cluster medoids
    5. Stores new cluster information back to database
    
    Args:
        eps (float): The maximum distance between two samples for one to be considered
                    as in the neighborhood of the other. Default is 0.1
        min_samples (int): The number of samples in a neighborhood for a point to be 
                          considered as a core point. Default is 1
        min_cluster_size (int): The minimum size of clusters. Default is 1
    
    Returns:
        numpy.ndarray: A similarity matrix of cluster medoids where each element [i,j]
                      represents the cosine similarity between medoids i and j
    """
    def reclusterPipeline(self, eps: float = 0.1, min_samples: int = 1, min_cluster_size: int = 1):
        texts = self.weaviate_client.get_all_embeddings(CollectionNames.TEXT.value)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)

        # Generate embeddings for each text entry and collect UUIDs
        embeddings_list = np.vstack([text["vector"] for text in texts])
        embeddings_uuids = np.array([text["properties"]["text_id"] for text in texts])

        # Cluster texts and get cluster medoids
        labels, centroids, medoids = apply_hdbscan(
            embeddings_list,
            eps=eps,
            min_samples=min_samples,
            metric=SimilarityMetric.cosine.value,
            min_cluster_size=min_cluster_size
        )

        # Compute pairwise cosine similarities between medoids
        similarity_matrix = cosine_similarity(medoids)

        # TODO: Delete all of the clusters here
        # Expose clusters and similarity matrix as instance variables
        for index in range(len(medoids)):
            cluster = { "properties": [{
                "cluster_id": "",
                "name": str(index),
                "members": embeddings_uuids[labels == index].tolist(),
                }]}
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, medoids[index].tolist(), cluster)

        # Return the similarity matrix
        return similarity_matrix


    """
    NewTextPipeline handles embedding generation for a single text input,  computes its similarity against existing cluster medoids,
    and persists the association in Weaviate.

    Args:
        text (str): The input text to embed and process.
        uuid (str): A unique identifier for the input text.

    Attributes:
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
    def newTextPipeline(self, text: str, uuid: str):
        embedding_id, embedding = generate_embeddings_local(uuid, text)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        similarity_scores = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
        best_medoid_idx = int(np.argmax(similarity_scores))

        properties = { "properties": [{
                    "text_id": uuid,
                    "text": text ,
                    "competencyIDs": clusters[best_medoid_idx]["properties"]["cluster_id"]
        } ] }
        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)
        return similarity_scores