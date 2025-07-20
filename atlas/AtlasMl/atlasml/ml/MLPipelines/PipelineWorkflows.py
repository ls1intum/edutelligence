import uuid
import numpy as np
import uuid
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames, WeaviateClient
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings, generate_embeddings_local
from atlasml.ml.VectorEmbeddings.MainEmbeddingModel import generate_embeddings_openai
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity
from atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension
from atlasml.models.competency import Competency, ExerciseWithCompetencies

class PipelineWorkflows:
    def __init__(self, weaviate_client=None):
        if weaviate_client is None:
            weaviate_client = get_weaviate_client()
        self.weaviate_client = weaviate_client

    def initial_texts(self, exercises: list[ExerciseWithCompetencies]):
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
        for exercise in exercises:
            embedding = generate_embeddings_local(exercise.title)
            properties = {
                "exercise_id": exercise.id,
                "title": exercise.title,
                "description": exercise.description,
                "competency_ids": [competency.id for competency in exercise.competencies]
            }
            self.weaviate_client.add_embeddings(CollectionNames.EXERCISE.value, embedding, properties)


    def initial_competencies(self, competencies: list[Competency]):
        """Process and store initial competencies in the database.

        Takes a list of competencies, generates embeddings for each competency, and stores them in
        the Weaviate competency collection. Each competency entry is created with a unique ID and 
        initialized with an empty cluster ID.

        Args:
            competencies (list[dict]): List of competency dictionaries containing 'title' and 'description'
        
        The workflow:
            1. For each competency:
            2. Generate a unique UUID
            3. Create vector embedding using the competency description
            4. Store in Weaviate competency collection with:
                - competency_id: Generated UUID
                - name: Competency title
                - cluster_id: Empty string
                - vector: Competency embedding
        """
        for competency in competencies:
            embedding = generate_embeddings_local(competency.title)
            properties = {
                "competency_id": competency.id,
                "name": competency.title,
                "description": competency.description,
            }
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)


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
        medoids = np.array([entry["vector"]["default"] for entry in clusters])
        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)

        for competency in competencies:
            uuid, embedding = generate_embeddings_local(competency["properties"]["competency_id"], competency["properties"]["text"])
            similarity_score = np.array([compute_cosine_similarity(embedding, medoid) for medoid in medoids])
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = {
                "competency_id": uuid,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"]
            }
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)


    def initial_cluster_pipeline(self):
        """
        Initialize and compute competency-centric clusters based on labeled data.
        This version uses existing exercise → competency mappings to build clusters.
        """

        # 1. Get all texts and competencies
        texts = self.weaviate_client.get_all_embeddings(CollectionNames.TEXT.value)
        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)

        # 2. Group texts by assigned competency
        competency_groups = {}
        for text in texts:
            competency_ids = text["properties"].get("competency_ids", [])
            for cid in competency_ids:
                if cid not in competency_groups:
                    competency_groups[cid] = []
                competency_groups[cid].append(text)

        # 3. Compute centroid embedding for each competency
        for competency in competencies:
            cid = competency["properties"]["competency_id"]
            related_texts = competency_groups.get(cid, [])
            if not related_texts:
                continue  # Skip if no texts available

            embeddings = np.vstack([t["vector"]["default"] for t in related_texts])
            centroid = np.mean(embeddings, axis=0)

            # Store centroid as a cluster center
            cluster_properties = {
                "cluster_id": cid  # Same as competency_id
            }
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, centroid.tolist(), cluster_properties)

            # Update the competency object with cluster_id and centroid similarity = 1.0
            competency_update = {
                "competency_id": cid,
                "name": competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "cluster_id": cid,
                "cluster_similarity_score": 1.0
            }
            self.weaviate_client.update_property_by_id(CollectionNames.COMPETENCY.value, competency["id"], competency_update)

        # 4. Update each text with the most similar competency (optional if already linked)
        all_centroids = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        for text in texts:
            text_embedding = text["vector"]["default"]
            similarities = [
                (compute_cosine_similarity(text_embedding, centroid["vector"]["default"]), centroid["properties"]["cluster_id"])
                for centroid in all_centroids
            ]
            similarities.sort(reverse=True)  # descending by similarity

            best_similarity, best_cid = similarities[0]
            updated_properties = {
                "text_id": text["properties"]["text_id"],
                "text": text["properties"]["text"],
                "competency_ids": [best_cid],
                "cluster_similarity_score": best_similarity
            }
            self.weaviate_client.update_property_by_id(CollectionNames.TEXT.value, text["id"], updated_properties)


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
        medoids = np.array([entry["vector"]["default"] for entry in clusters])
        similarity_scores = np.array([compute_cosine_similarity(embedding, medoid) for medoid in medoids])
        best_medoid_idx = int(np.argmax(similarity_scores))
        competency = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", clusters[best_medoid_idx]["properties"]["cluster_id"])
        competency_to_match = None
        if competency: competency_to_match = competency[0]

        properties = {
                    "text_id": uuid,
                    "text": text ,
                    "competency_ids": [competency_to_match["properties"]["competency_id"]]
        }
        self.weaviate_client.add_embeddings(CollectionNames.TEXT.value, embedding, properties)
        return competency_to_match["properties"]["competency_id"]