import uuid
import numpy as np
import uuid

from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml import update_cluster_centroid_on_removal, update_cluster_centroid
from atlasml.ml.clustering import apply_hdbscan, SimilarityMetric, apply_kmeans
from atlasml.ml.embeddings import generate_embeddings_openai
from atlasml.ml.similarity_measures import compute_cosine_similarity
from atlasml.models.competency import (
    ExerciseWithCompetencies,
    Competency,
    OperationType, ClusterCenters,
)
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
            "description": competency.description,
            "course_id": competency.course_id,
        }
        self.weaviate_client.add_embeddings(
            CollectionNames.COMPETENCY.value, embedding, properties
        )

    def save_exercise_to_weaviate(self, exercise: ExerciseWithCompetencies):
        embedding = generate_embeddings_openai(exercise.description)
        properties = {
            "exercise_id": exercise.id,
            "description": exercise.description,
            "competency_ids": exercise.competencies,
            "course_id": exercise.course_id,
        }
        self.weaviate_client.add_embeddings(
            CollectionNames.EXERCISE.value, embedding, properties
        )

    def initial_exercises(self, exercises: list[ExerciseWithCompetencies]):
        """Process and store initial text entries in the database. """
        for exercise in exercises:
            self.save_exercise_to_weaviate(exercise)

    def initial_competencies(self, competencies: list[Competency]):
        """Process and store initial competencies in the database. """
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

        clusters = self.weaviate_client.get_all_embeddings(
            CollectionNames.CLUSTERCENTER.value
        )
        medoids = np.array([entry["vector"]["default"] for entry in clusters])
        competencies = self.weaviate_client.get_all_embeddings(
            CollectionNames.COMPETENCY.value
        )

        for competency in competencies:
            embedding = generate_embeddings_openai(
                competency["properties"]["description"]
            )
            similarity_score = np.array(
                [compute_cosine_similarity(embedding, medoid) for medoid in medoids]
            )
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = {
                "competency_id": competency["properties"]["competency_id"],
                "title": competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": similarity_score[best_medoid_idx],
            }
            self.weaviate_client.add_embeddings(
                CollectionNames.COMPETENCY.value, embedding, properties
            )

    def initial_cluster_pipeline(
        self, eps: float = 0.1, min_samples: int = 1, min_cluster_size: int = 2
    ):
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
        exercises = self.weaviate_client.get_all_embeddings(
            CollectionNames.EXERCISE.value
        )

        # Generate embeddings for each exercise entry
        embeddings_list = np.vstack(
            [exercise["vector"]["default"] for exercise in exercises]
        )

        # Cluster texts and get cluster medoids
        labels, centroids, medoids = apply_hdbscan(
            embeddings_list,
            eps=eps,
            min_samples=min_samples,
            metric=SimilarityMetric.cosine.value,
            min_cluster_size=min_cluster_size,
        )

        # Expose clusters and similarity matrix as instance variables
        for index in range(len(medoids)):
            cluster = {"cluster_id": uuid.uuid4(), "label_id": str(index)}
            self.weaviate_client.add_embeddings(
                CollectionNames.CLUSTERCENTER.value, medoids[index].tolist(), cluster
            )

        competencies = self.weaviate_client.get_all_embeddings(
            CollectionNames.COMPETENCY.value
        )
        clusters = self.weaviate_client.get_all_embeddings(
            CollectionNames.CLUSTERCENTER.value
        )

        for competency in competencies:
            competency_id, embedding = (
                competency["properties"]["competency_id"],
                competency["vector"]["default"],
            )
            similarity_score = np.array(
                [compute_cosine_similarity(embedding, medoid) for medoid in medoids]
            )
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = {
                "competency_id": competency_id,
                "title": competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[best_medoid_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": similarity_score[best_medoid_idx],
            }
            self.weaviate_client.update_property_by_id(
                CollectionNames.COMPETENCY.value, competency["id"], properties
            )

        for index in range(len(exercises)):
            exercise = exercises[index]
            cluster_center = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.CLUSTERCENTER.value, "label_id", str(labels[index])
            )
            # TODO: Check cluster center is not empty
            if not cluster_center:
                continue
            competency = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.COMPETENCY.value,
                "cluster_id",
                cluster_center[0]["properties"]["cluster_id"],
            )
            if not competency:
                continue
            competency_id = competency[0]["properties"]["competency_id"]
            properties = {
                "exercise_id": exercise["properties"]["exercise_id"],
                "description": exercise["properties"]["description"],
                "competency_ids": [competency_id],
            }
            self.weaviate_client.update_property_by_id(
                CollectionNames.EXERCISE.value, exercise["id"], properties
            )

        return

    def save_competency(
        self,
        competency: Competency,
        operation_type: OperationType = OperationType.UPDATE,
    ):
        if operation_type == OperationType.DELETE:
            self.delete_competency(competency)
        else:  # UPDATE operation
            existing_competency = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.COMPETENCY.value, "competency_id", competency.id
            )
            if existing_competency:
                assert (
                    len(existing_competency) == 1
                ), "Multiple competencies found for the same ID"  # TODO: Throw error
                competency_to_update = existing_competency[0]
                embedings = generate_embeddings_openai(competency.description)
                properties = {
                    "competency_id": competency.id,
                    "title": competency.title,
                    "description": competency.description,
                    "course_id": competency.course_id,
                }
                self.weaviate_client.update_property_by_id(
                    CollectionNames.COMPETENCY.value,
                    competency_to_update["id"],
                    properties,
                    embedings,
                )
            else:
                self.save_competency_to_weaviate(competency)
            # Re-cluster after update
            self.recluster_with_new_competencies(competency=competency, course_id=competency.course_id)

    def delete_competency(self, competency: Competency):
        """Delete a competency from Weaviate and trigger re-clustering."""
        existing_competency = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "competency_id", competency.id
        )
        if existing_competency:
            assert (
                len(existing_competency) == 1
            ), "Multiple competencies found for the same ID"
            competency_to_delete = existing_competency[0]
            self.weaviate_client.delete_by_id(
                CollectionNames.COMPETENCY.value, competency_to_delete["id"]
            )
            # Re-cluster after deletion
            self.recluster_with_new_competencies(competency=competency, course_id=competency.course_id)
        else:
            logger.warning(f"Competency with id {competency.id} not found for deletion")

    def recluster_with_new_competencies(self, competency: Competency, course_id: str):
        # Get competencies and exercise embeddings
        competencies = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "course_id", course_id
        )
        if len(competencies) == 0: return
        exercises = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.EXERCISE.value, "course_id", course_id
        )
        if len(exercises) == 0: return

        # Delete all cluster centers for new centers
        # TODO: We need to use course_id to filter for course such as below
        # self.weaviate_client.delete_by_property(
        #     CollectionNames.CLUSTERCENTER.value, "course_id", course_id
        # )
        self.weaviate_client.delete_all_data_from_collection(CollectionNames.CLUSTERCENTER.value)

        exercise_embeddings = np.vstack(
            [exercise["vector"]["default"] for exercise in exercises]
        )
        # Cluster texts and get cluster centroids
        labels, centroids = apply_kmeans(
            matrix=exercise_embeddings,
            n_clusters=len(competencies)
        )

        # Expose clusters
        for index in range(len(centroids)):
            cluster = {"cluster_id": uuid.uuid4(), "label_id": str(index)}
            self.weaviate_client.add_embeddings(
                CollectionNames.CLUSTERCENTER.value, centroids[index].tolist(), cluster
            )

        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)

        # Calculate similarity matrix for all competencies to all centroids
        competency_embeddings = np.array([comp["vector"]["default"] for comp in competencies])
        similarity_matrix = np.array([
            [compute_cosine_similarity(comp_emb, centroid)
             for centroid in centroids]
            for comp_emb in competency_embeddings
        ])

        # Use Hungarian algorithm or greedy approach for optimal 1-to-1 assignment
        used_clusters = set()
        competency_assignments = []

        # Sort competencies by their best similarity scores (descending)
        competency_indices = list(range(len(competencies)))
        competency_indices.sort(key=lambda i: np.max(similarity_matrix[i]), reverse=True)

        for comp_idx in competency_indices:
            # Find the best available cluster for this competency
            available_clusters = [i for i in range(len(centroids)) if i not in used_clusters]
            if not available_clusters:
                raise ValueError("Not enough clusters for all competencies")

            best_cluster_idx = max(available_clusters,
                                   key=lambda i: similarity_matrix[comp_idx][i])

            competency_assignments.append((comp_idx, best_cluster_idx))
            used_clusters.add(best_cluster_idx)

        # Update competencies with their assigned clusters
        for comp_idx, cluster_idx in competency_assignments:
            competency = competencies[comp_idx]
            competency_id = competency["properties"]["competency_id"]
            similarity_score = similarity_matrix[comp_idx][cluster_idx]

            properties = {
                "competency_id": competency_id,
                "title": competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[cluster_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": float(similarity_score),
            }
            self.weaviate_client.update_property_by_id(
                CollectionNames.COMPETENCY.value, competency["id"], properties
            )
        return

    def new_text_suggestion(
            self, exercise_description: str, course_id: str
    ) -> list[tuple[Competency, float]]:
        """Process a new text entry and associate it with existing clusters."""
        exercise_embedding = generate_embeddings_openai(exercise_description)
        clusters = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.CLUSTERCENTER.value, "course_id", course_id
        )

        if not clusters:
            logger.warning("No clusters found in database")
            return []
        else:
            # There are clusters which also mean that there are competencies
            cluster_centers = [
                ClusterCenters(cluster_id=str(entry["properties"]["cluster_id"]),
                               course_id=entry["properties"]["course_id"],
                               vector_embedding=entry["vector"]["default"])
                for entry in clusters
            ]
            similarities_with_indices: list[tuple[float, ClusterCenters]] =  [
                (compute_cosine_similarity(exercise_embedding, cluster.vector_embedding), cluster)
                for cluster in cluster_centers
            ]
            similarities_with_indices.sort(key=lambda x: x[0], reverse=True)  # Sort by similarity score descending

            top3_competencies = []
            for similarity_score, best_medoid  in similarities_with_indices[:3]:
                competency = self.weaviate_client.get_embeddings_by_property(
                    CollectionNames.COMPETENCY.value,
                    "cluster_id",
                    best_medoid.cluster_id
                )
                best_competency = Competency(
                    id=competency[0]["properties"]["competency_id"],
                    title=competency[0]["properties"]["title"],
                    description=competency[0]["properties"]["description"],
                    course_id=competency[0]["properties"].get("course_id", "unknown"),
                )
                top3_competencies.append((best_competency, similarity_score))

            return top3_competencies

    def suggest_competencies_by_similarity(
        self, exercise_description: str, course_id: str, top_k: int = 3
    ) -> list[Competency]:
        """Suggest competencies based on embedding similarity without re-clustering.

        Args:
            exercise_description: Description of the exercise to find similar competencies for
            course_id: Course ID to filter competencies by
            top_k: Number of top similar competencies to return (default: 5)

        Returns:
            List of most similar competencies ordered by similarity score
        """
        top_competencies_with_similarity_scores = self.new_text_suggestion(exercise_description, course_id)
        top_competencies = [competency for competency, similarity_score in top_competencies_with_similarity_scores]

        logger.info(
            f"Found {len(top_competencies_with_similarity_scores)} similar competencies for exercise description"
        )
        return top_competencies

    def save_exercise(
        self,
        exercise: ExerciseWithCompetencies,
        operation_type: OperationType = OperationType.UPDATE,
    ):
        if operation_type == OperationType.DELETE:
            self.delete_exercise(exercise)
        else:  # UPDATE operation
            existing_exercise = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.EXERCISE.value, "exercise_id", exercise.id
            )
            if existing_exercise:
                assert (
                    len(existing_exercise) == 1
                ), "Multiple exercises found for the same ID"  # TODO: Throw error
                exercise_to_update = existing_exercise[0]
                embeddings = generate_embeddings_openai(exercise.description)
                self.instructor_feedback(exercise, embeddings, exercise_to_update)
                properties = {
                    "exercise_id": exercise.id,
                    "description": exercise.description,
                    "competency_ids": exercise.competencies,
                    "course_id": exercise.course_id,
                }
                self.weaviate_client.update_property_by_id(
                    CollectionNames.EXERCISE.value,
                    exercise_to_update["id"],
                    properties,
                    embeddings,
                )
            else:
                self.save_exercise_to_weaviate(exercise)

    def delete_exercise(self, exercise: ExerciseWithCompetencies):
        """Delete an exercise from Weaviate."""
        existing_exercise = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.EXERCISE.value, "exercise_id", exercise.id
        )
        if existing_exercise:
            assert (
                len(existing_exercise) == 1
            ), "Multiple exercises found for the same ID"
            exercise_to_delete = existing_exercise[0]
            self.weaviate_client.delete_by_id(
                CollectionNames.EXERCISE.value, exercise_to_delete["id"]
            )
        else:
            logger.warning(f"Exercise with id {exercise.id} not found for deletion")

    def instructor_feedback(
            self,
            updated_exercise: ExerciseWithCompetencies,
            updated_exercise_embedding: list[float],
            old_exercise,
    ):
        old_exercise_with_competencies = ExerciseWithCompetencies(
            id=old_exercise["properties"]["exercise_id"],
            title="",
            description=old_exercise["properties"]["description"],
            competencies=old_exercise["properties"]["competency_ids"],
            course_id=old_exercise["properties"]["course_id"]
        )

        # Get competency IDs from both exercises
        old_competency_ids = set(old_exercise_with_competencies.competencies)
        updated_competency_ids = set(updated_exercise.competencies)

        # Find differences in terms of competencies
        added_competencies = updated_competency_ids - old_competency_ids
        removed_competencies = old_competency_ids - updated_competency_ids
        unchanged_competencies = old_competency_ids & updated_competency_ids

        logger.info(f"Competency analysis for exercise {updated_exercise.id}:")

        # Process removed and added competencies
        if removed_competencies:
            self.update_cluster_for_competencies(updated_exercise_embedding, removed_competencies, is_removal=True)
            logger.info(f"Removed competencies: {list(removed_competencies)}")

        if added_competencies:
            self.update_cluster_for_competencies(updated_exercise_embedding, added_competencies, is_removal=False)
            logger.info(f"Added competencies: {list(added_competencies)}")

    def update_cluster_for_competencies(
            self,
            exercise_embedding,
            competency_ids,
            is_removal=False
    ):
        """Helper function to update cluster centroids for a set of competencies."""
        for comp_id in competency_ids:
            # Get the competency and its cluster
            competency_data = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.COMPETENCY.value, "competency_id", comp_id
            )
            if not competency_data:
                continue

            cluster_id = competency_data[0]["properties"]["cluster_id"]

            # Get current cluster centroid
            cluster_data = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.CLUSTERCENTER.value, "cluster_id", cluster_id
            )
            if not cluster_data:
                continue

            current_centroid = np.array(cluster_data[0]["vector"]["default"])

            # Count exercises currently in this cluster
            exercises_in_cluster = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.EXERCISE.value, "competency_ids", comp_id
            )
            cluster_size = len(exercises_in_cluster)

            # Update centroid based on operation type
            if is_removal:
                if cluster_size > 1:
                    updated_centroid = update_cluster_centroid_on_removal(
                        current_centroid, cluster_size, exercise_embedding
                    )
                    action = "removed"
                else:
                    continue
            else:
                cluster_size -= 1
                updated_centroid = update_cluster_centroid(
                    current_centroid, cluster_size, exercise_embedding
                )
                action = "added"

            # Update the cluster centroid in Weaviate
            self.weaviate_client.update_property_by_id(
                CollectionNames.CLUSTERCENTER.value,
                cluster_data[0]["id"],
                cluster_data[0]["properties"],
                updated_centroid.tolist()
            )
            logger.info(f"Updated cluster centroid for {action} competency {comp_id}")
