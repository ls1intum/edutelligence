import uuid
import numpy as np
import uuid
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames, WeaviateClient
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity
from atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


class PipelineWorkflows:
    def __init__(self):
        self.weaviate_client = get_weaviate_client()

    def initial_texts(self, texts: list[str]):
        """Process and store initial text entries in the database.

        Takes a list of texts, generates embeddings for each one, and stores them
        in the Weaviate database with unique IDs and empty competency associations.

        Args:
            texts (list[str]): List of text strings to be processed and stored.

        Note:
            Each text is stored with:
            - A randomly generated UUID
            - The original text content
            - An empty competencyIDs list
            - Its vector embedding
        """
        for text in texts:
            text_id, embedding = generate_embeddings_local(str(uuid.uuid4()), text)
            properties = {"properties": [{
                "text_id": text_id,
                "text": text,
                "competencyIDs": []
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)


    def initial_cluster_to_competencyPipeline(self):
        """Associate competencies with their closest cluster medoids.

        Processes all competencies in the database and assigns them to their most
        similar cluster based on cosine similarity with cluster medoids.

        The process includes:
        1. Fetching all cluster medoids from the database
        2. Fetching all competencies
        3. For each competency:
            - Generating its embedding
            - Finding the most similar cluster medoid
            - Storing the association in the database

        Note:
            Updates the COMPETENCY collection with new embeddings and cluster associations.
        """

        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)

        for competency in competencies:
            uuid, embedding = generate_embeddings_local(competency["properties"]["competency_id"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "competency_id": uuid ,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "clusterID": clusters[best_medoid_idx]["properties"]["cluster_id"]
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)


    def initial_cluster_pipeline(self, eps: float = 0.1, min_samples: int = 1, min_cluster_size: int = 1):
        """Initialize and perform complete clustering of all texts in the database.

        This is the main pipeline for clustering text data and establishing relationships
        between texts and competencies through clusters.

        Args:
            eps (float, optional): Maximum distance between points for HDBSCAN clustering.
                Defaults to 0.1.
            min_samples (int, optional): Minimum number of samples in a neighborhood.
                Defaults to 1.
            min_cluster_size (int, optional): Minimum number of points to form a cluster.
                Defaults to 1.

        The pipeline performs:
        1. Text embedding retrieval
        2. HDBSCAN clustering of embeddings
        3. Cluster center calculation and storage
        4. Competency-to-cluster association
        5. Text-to-competency linking

        Note:
            - Deletes all existing cluster centers before creating new ones
            - Updates both COMPETENCY and TEXT collections with new associations
        """
        texts = self.weaviate_client.get_all_embeddings(CollectionNames.TEXT.value)

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

        self.weaviate_client.delete_all_data_from_collection(CollectionNames.CLUSTERCENTER.value)
        # Expose clusters and similarity matrix as instance variables
        for index in range(len(medoids)):
            cluster = { "properties": [{
                "cluster_id": str(uuid.uuid4())
                # "members": embeddings_uuids[labels == index].tolist(),
                }]}
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, medoids[index].tolist(), cluster)

        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)

        for competency in competencies:
            competency_id, embedding = generate_embeddings_local(competency["properties"]["competency_id"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "competency_id": competency_id,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "clusterID": clusters[best_medoid_idx]["properties"]["cluster_id"]
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)

        for index in range(len(texts)):
            text_entry = texts[index]
            competency_id = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", labels[index])["properties"]["competency_id"]
            properties = {"properties": [{
                "text_id": text_entry["properties"]["text_id"],
                "text": text_entry["properties"]["text"],
                "competencyIDs": [competency_id]
            }]}
            self.weaviate_client.update_property_by_id(CollectionNames.TEXT.value, text_entry["properties"]["text_id"], properties)

        return


    def newTextPipeline(self, text: str, uuid: str):
        """Process a new text entry and associate it with existing clusters.

        Takes a single text input, computes its embedding, and assigns it to the
        most similar existing cluster based on medoid similarity.

        Args:
            text (str): The text content to be processed
            uuid (str): Unique identifier for the text entry

        Returns:
            str: The competency ID of the best matching competency

        The process includes:
        1. Generating embedding for the input text
        2. Finding the most similar cluster medoid
        3. Retrieving the associated competency
        4. Storing the text with its competency association

        Note:
            Adds the new text entry to the TEXT collection with its embedding
            and competency association.
        """
        embedding_id, embedding = generate_embeddings_local(uuid, text)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        similarity_scores = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
        best_medoid_idx = int(np.argmax(similarity_scores))
        competency_to_match = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", clusters[best_medoid_idx]["properties"]["cluster_id"])[0]

        properties = { "properties": [{
                    "text_id": uuid,
                    "text": text ,
                    "competencyIDs": competency_to_match["properties"]["competency_id"]
        } ] }
        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)
        return competency_to_match["properties"]["competency_id"]