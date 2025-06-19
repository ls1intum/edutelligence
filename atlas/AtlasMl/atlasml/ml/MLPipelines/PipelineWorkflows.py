import uuid
import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames, WeaviateClient
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.FeedbackLoop.FeedbackLoop import update_cluster_centroid
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings
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
            text_id, embedding = generate_embeddings(str(uuid.uuid4()), text)
            properties = {"properties": [{
                "text_id": text_id,
                "text": text,
                "competency_ids": []
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
            uuid, embedding = generate_embeddings(competency["properties"]["competency_id"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "competency_id": uuid ,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"]
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
                }]}
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, medoids[index].tolist(), cluster)

        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)

        for competency in competencies:
            competency_id, embedding = generate_embeddings(competency["properties"]["competency_id"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "competency_id": competency_id,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"]
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)

        for index in range(len(texts)):
            text_entry = texts[index]
            competency_id = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", labels[index])["properties"]["competency_id"]
            properties = {"properties": [{
                "text_id": text_entry["properties"]["text_id"],
                "text": text_entry["properties"]["text"],
                "competency_ids": [competency_id]
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
        embedding_id, embedding = generate_embeddings(uuid, text)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array(entry["vector"] for entry in clusters)
        similarity_scores = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
        best_medoid_idx = int(np.argmax(similarity_scores))
        competency_to_match = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", clusters[best_medoid_idx]["properties"]["cluster_id"])[0]

        properties = { "properties": [{
                    "text_id": uuid,
                    "text": text ,
                    "competency_ids": competency_to_match["properties"]["competency_id"]
        } ] }
        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)
        return competency_to_match["properties"]["competency_id"]


    def feedbackLoopPipeline(self, text_id: str, cluster_id: str):
        """Update text-cluster associations based on feedback and recalculate cluster medoids.

        This function implements a feedback loop mechanism that allows updating text-cluster
        associations and dynamically adjusts cluster medoids based on new assignments.

        Args:
            text_id (str): The unique identifier of the text entry to be reassigned
            cluster_id (str): The identifier of the cluster to which the text should be assigned

        The pipeline performs:
        1. Retrieves the text entry and target cluster from the database
        2. Updates the text's competency associations to include the new cluster
        3. Updates the cluster's member list to include the text
        4. Recalculates the cluster medoid considering the new text
        5. Persists all changes back to the database

        Note:
            - This function modifies both TEXT and CLUSTERCENTER collections
            - The text's previous competency associations are preserved
            - The cluster medoid is updated using a weighted average approach
            - All changes are atomic - either all succeed or none are applied

        Warning:
            Ensure both text_id and cluster_id exist in the database before calling
            this function to avoid potential errors.
        """
        text = self.weaviate_client.get_embeddings_by_property(CollectionNames.TEXT.value, "text_id", text_id)
        cluster = self.weaviate_client.get_embeddings_by_property(CollectionNames.CLUSTERCENTER.value, "cluster_id", cluster_id)

        new_text_competencyID = text["properties"]["competencyIDs"]
        new_text_competencyID.append(cluster_id)

        new_text = { "properties": [{
                    "text_id":  text["properties"]["text_id"],
                    "text":  text["properties"]["text"] ,
                    "competencyIDs": new_text_competencyID
        }]}

        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, text["vector"], new_text)

        new_members = cluster["properties"]["members"]
        new_members.append(text_id)

        newMedoid = update_cluster_centroid(cluster["vector"], len(new_members) - 1, text["vector"])

        new_cluster = {"properties": [{
            "cluster_id": cluster["properties"]["cluster_id"],
            "name": cluster["properties"]["name"],
            "members": new_members,
        }]}
        self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, newMedoid.tolist(), new_cluster)
