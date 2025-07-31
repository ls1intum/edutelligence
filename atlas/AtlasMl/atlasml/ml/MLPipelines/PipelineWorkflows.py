import uuid
import numpy as np
import uuid
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.VectorEmbeddings.MainEmbeddingModel import generate_embeddings_openai
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from atlasml.models.competency import ExerciseWithCompetencies, Competency, CompetencyTaxonomy
import logging

logger = logging.getLogger(__name__)


class PipelineWorkflows:
    def __init__(self, weaviate_client=None):
        if weaviate_client is None:
            weaviate_client = get_weaviate_client()
        self.weaviate_client = weaviate_client
        self.weaviate_client._ensure_collections_exist()


    def save_competency_to_weaviate(self, competency: Competency):
        embedding = generate_embeddings_openai(competency.description)
        properties = {
            "competency_id": competency.id,
            "title": competency.title,
            "description": competency.description
        }
        self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)

    def save_exercise_to_weaviate(self, exercise: ExerciseWithCompetencies):
        embedding = generate_embeddings_openai(exercise.description)
        properties = {
            "exercise_id": exercise.id,
            "description": exercise.description,
            "competency_ids": exercise.competencies
        }
        self.weaviate_client.add_embeddings(CollectionNames.EXERCISE.value, embedding, properties)

    def initial_exercises(self, exercises: list[ExerciseWithCompetencies]):
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
            self.save_exercise_to_weaviate(exercise)

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
                - title: Competency title
                - description: Competency description
                - cluster_id: Empty string
                - vector: Competency embedding
        """
        for competency in competencies:
            self.save_competency_to_weaviate(competency)


    def initial_cluster_to_competency_pipeline(self):
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
            embedding = generate_embeddings_openai(competency["properties"]["description"])
            similarity_score = np.array([compute_cosine_similarity(embedding, medoid) for medoid in medoids])
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = {
                "competency_id": competency["properties"]["competency_id"],
                "title" : competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": similarity_score[best_medoid_idx]
            }
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)


    def initial_cluster_pipeline(self, eps: float = 0.1, min_samples: int = 1, min_cluster_size: int = 2):
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
        exercises = self.weaviate_client.get_all_embeddings(CollectionNames.EXERCISE.value)

        # Generate embeddings for each exercise entry
        embeddings_list = np.vstack([exercise["vector"]["default"] for exercise in exercises])

        # Cluster texts and get cluster medoids
        labels, centroids, medoids = apply_hdbscan(
            embeddings_list,
            eps=eps,
            min_samples=min_samples,
            metric=SimilarityMetric.cosine.value,
            min_cluster_size=min_cluster_size
        )

        # Expose clusters and similarity matrix as instance variables
        for index in range(len(medoids)):
            cluster = {
                    "cluster_id": uuid.uuid4(),
                    "label_id": str(index)
                    }
            self.weaviate_client.add_embeddings(CollectionNames.CLUSTERCENTER.value, medoids[index].tolist(), cluster)

        competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)

        for competency in competencies:
            competency_id, embedding = competency["properties"]["competency_id"], competency["vector"]["default"]
            similarity_score = np.array([compute_cosine_similarity(embedding, medoid) for medoid in medoids])
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = {
                "competency_id": competency_id,
                "title" : competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": similarity_score[best_medoid_idx]
            }
            self.weaviate_client.update_property_by_id(CollectionNames.COMPETENCY.value, competency["id"], properties)

        for index in range(len(exercises)):
            exercise = exercises[index]
            cluster_center = self.weaviate_client.get_embeddings_by_property(CollectionNames.CLUSTERCENTER.value, "label_id", str(labels[index]))
            # TODO: Check cluster center is not empty
            if not cluster_center: continue
            competency = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", cluster_center[0]["properties"]["cluster_id"])
            if not competency: continue
            competency_id = competency[0]["properties"]["competency_id"]
            properties = {
                "exercise_id": exercise["properties"]["exercise_id"],
                "description": exercise["properties"]["description"],
                "competency_ids": [competency_id]
            }
            self.weaviate_client.update_property_by_id(CollectionNames.EXERCISE.value, exercise["id"], properties)

        return


    def newTextPipeline(self, text: str) -> Competency:
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
        embedding = generate_embeddings_openai(text)
        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
        medoids = np.array([entry["vector"]["default"] for entry in clusters])
        similarity_scores = np.array([compute_cosine_similarity(embedding, medoid) for medoid in medoids])


        # TODO: @ArdaKaraman Currently returns the best match, but we should return the top 3 matches (To be discussed)
        best_medoid_idx = int(np.argmax(similarity_scores))
        competency = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "cluster_id", clusters[best_medoid_idx]["properties"]["cluster_id"])
        if not competency: return None
        best_competency = Competency(
            id=competency[0]["properties"]["competency_id"],
            title=competency[0]["properties"]["title"],
            description=competency[0]["properties"]["description"],
            taxonomy=CompetencyTaxonomy.UNDERSTAND
        )
        return best_competency
    

    def save_competency(self, competency: Competency):
        existing_competency = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "competency_id", competency.id)
        if existing_competency:
            assert len(existing_competency) == 1, "Multiple competencies found for the same ID" # TODO: Throw error 
            competency_to_update = existing_competency[0]
            embedings = generate_embeddings_openai(competency.description)
            properties = {
                "competency_id": competency.id,
                "title": competency.title,
                "description": competency.description
            }
            self.weaviate_client.update_property_by_id(CollectionNames.COMPETENCY.value, competency_to_update["id"], properties, embedings)
        else:
            self.save_competency_to_weaviate(competency)

        
        self.weaviate_client.delete_all_data_from_collection(CollectionNames.CLUSTERCENTER.value)
        self.initial_cluster_pipeline()
        self.initial_cluster_to_competency_pipeline()
    
    def save_exercise(self, exercise: ExerciseWithCompetencies):
        existing_exercise = self.weaviate_client.get_embeddings_by_property(CollectionNames.EXERCISE.value, "exercise_id", exercise.id)
        if existing_exercise:
            assert len(existing_exercise) == 1, "Multiple exercises found for the same ID" # TODO: Throw error 
            exercise_to_update = existing_exercise[0]
            embedings = generate_embeddings_openai(exercise.description)
            properties = {
                "exercise_id": exercise.id,
                "description": exercise.description,
                "competency_ids": exercise.competencies
            }
            self.weaviate_client.update_property_by_id(CollectionNames.EXERCISE.value, exercise_to_update["id"], properties, embedings)
        else:
            self.save_exercise_to_weaviate(exercise)

        self.weaviate_client.delete_all_data_from_collection(CollectionNames.CLUSTERCENTER.value)
        self.initial_cluster_pipeline()
        self.initial_cluster_to_competency_pipeline()