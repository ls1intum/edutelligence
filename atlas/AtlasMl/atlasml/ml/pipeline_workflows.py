import uuid
from typing import Optional

import numpy as np
import uuid

from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml import update_cluster_centroid_on_removal, update_cluster_centroid_on_addition
from atlasml.ml.clustering import apply_hdbscan, SimilarityMetric, apply_kmeans
from atlasml.ml.embeddings import generate_embeddings_openai
from atlasml.ml.generate_competency_relationship import generate_competency_relationship
from atlasml.ml.similarity_measures import compute_cosine_similarity
from atlasml.models.competency import (
    ExerciseWithCompetencies,
    Competency,
    OperationType, SemanticCluster, CompetencyRelation, CompetencyRelationSuggestionResponse, RelationType,
)
import logging

logger = logging.getLogger(__name__)


class PipelineWorkflows:
    def __init__(self, weaviate_client=None):
        if weaviate_client is None:
            weaviate_client = get_weaviate_client()
        self.weaviate_client = weaviate_client
        self.weaviate_client._ensure_collections_exist()



    def map_new_competency_to_exercise(
            self,
            exercise_id: int,
            competency_id: int
    ):
        exercise_data = self.weaviate_client.get_embeddings_by_property(CollectionNames.EXERCISE.value, "exercise_id", exercise_id)
        competency_data = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "competency_id", competency_id)

        if not exercise_data or not competency_data:
            raise ValueError("No exercise or competency found for mapping")

        exercise = ExerciseWithCompetencies(
            id=int(exercise_data[0]["properties"]["exercise_id"]),
            title=exercise_data[0]["properties"].get("title", ""),
            description=exercise_data[0]["properties"]["description"],
            competencies=exercise_data[0]["properties"]["competency_ids"],
            course_id=exercise_data[0]["properties"]["course_id"],
        )
        competency = Competency(
            id=int(competency_data[0]["properties"]["competency_id"]),
            title=competency_data[0]["properties"]["title"],
            description=competency_data[0]["properties"]["description"],
            course_id=int(competency_data[0]["properties"]["course_id"]),
        )

        if competency.id not in exercise.competencies:
            exercise.competencies.append(competency.id)

        properties = {
            "exercise_id": exercise.id,
            "description": exercise.description,
            "competency_ids": exercise.competencies,
            "course_id": exercise.course_id,
        }
        self.weaviate_client.update_property_by_id(
            CollectionNames.EXERCISE.value, exercise_data[0]["id"], properties
        )

    def map_competency_to_competency(
            self,
            source_competency_id: int,
            target_competency_id: int
    ):
        source_competency_data = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "competency_id", source_competency_id
        )
        target_competency_data = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "competency_id", target_competency_id
        )

        if not source_competency_data or not target_competency_data:
            raise ValueError("Source or target competency not found for mapping")

        # Get existing related competencies and normalize to list of ints
        source_related_raw = source_competency_data[0]["properties"].get("related_competencies", [])
        target_related_raw = target_competency_data[0]["properties"].get("related_competencies", [])

        # Convert to list of ints, filtering out non-convertible entries
        source_related = []
        for item in source_related_raw:
            try:
                source_related.append(int(item))
            except (ValueError, TypeError):
                continue

        target_related = []
        for item in target_related_raw:
            try:
                target_related.append(int(item))
            except (ValueError, TypeError):
                continue

        # Add bidirectional relationship if not already exists
        if target_competency_id not in source_related:
            source_related.append(target_competency_id)
        if source_competency_id not in target_related:
            target_related.append(source_competency_id)

        # Update source competency
        source_properties = {
            "competency_id": int(source_competency_data[0]["properties"]["competency_id"]),
            "title": source_competency_data[0]["properties"]["title"],
            "description": source_competency_data[0]["properties"]["description"],
            "course_id": source_competency_data[0]["properties"]["course_id"],
            "related_competencies": source_related,
        }
        if "cluster_id" in source_competency_data[0]["properties"]:
            source_properties["cluster_id"] = source_competency_data[0]["properties"]["cluster_id"]
        if "cluster_similarity_score" in source_competency_data[0]["properties"]:
            source_properties["cluster_similarity_score"] = source_competency_data[0]["properties"]["cluster_similarity_score"]
        self.weaviate_client.update_property_by_id(
            CollectionNames.COMPETENCY.value, source_competency_data[0]["id"], source_properties
        )

        # Update target competency
        target_properties = {
            "competency_id": int(target_competency_data[0]["properties"]["competency_id"]),
            "title": target_competency_data[0]["properties"]["title"],
            "description": target_competency_data[0]["properties"]["description"],
            "course_id": target_competency_data[0]["properties"]["course_id"],
            "related_competencies": target_related,
        }
        if "cluster_id" in target_competency_data[0]["properties"]:
            target_properties["cluster_id"] = target_competency_data[0]["properties"]["cluster_id"]
        if "cluster_similarity_score" in target_competency_data[0]["properties"]:
            target_properties["cluster_similarity_score"] = target_competency_data[0]["properties"]["cluster_similarity_score"]
        self.weaviate_client.update_property_by_id(
            CollectionNames.COMPETENCY.value, target_competency_data[0]["id"], target_properties
        )


    def save_competency_to_weaviate(self, competency: Competency):
        embedding = generate_embeddings_openai(competency.description if competency.description else competency.title)
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
            "title": exercise.title,
            "description": exercise.description,
            "competency_ids": [comp_id for comp_id in exercise.competencies] if exercise.competencies else [],
            "course_id": exercise.course_id,
        }
        logger.info(f"EXERCISE PROPERTIES: {properties}")
        self.weaviate_client.add_embeddings(
            CollectionNames.EXERCISE.value, embedding, properties
        )
        return embedding

    def initial_exercises(self, exercises: list[ExerciseWithCompetencies]):
        """Process and store initial text entries in the database. """
        for exercise in exercises:
            self.save_exercise_to_weaviate(exercise)

    def initial_competencies(self, competencies: list[Competency]):
        """Process and store initial competencies in the database. """
        for competency in competencies:
            self.save_competency_to_weaviate(competency)

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
            logger.info(f"Existing competency: {existing_competency}")
            if existing_competency:
                assert (
                    len(existing_competency) == 1
                ), "Multiple competencies found for the same ID"  # TODO: Throw error
                competency_to_update = existing_competency[0]
                embedings = generate_embeddings_openai(competency.description if competency.description else competency.title)
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

    def save_competencies(
        self,
        competencies: list[Competency],
        operation_type: OperationType = OperationType.UPDATE,
    ):
        if not competencies:
            return

        course_id = competencies[0].course_id

        # Save all competencies first
        for competency in competencies:
            if operation_type == OperationType.DELETE:
                self.delete_competency(competency)
            else:  # UPDATE operation
                existing_competency = self.weaviate_client.get_embeddings_by_property(
                    CollectionNames.COMPETENCY.value, "competency_id", competency.id
                )
                logger.info(f"Existing competency: {existing_competency}")
                if existing_competency:
                    assert (
                        len(existing_competency) == 1
                    ), "Multiple competencies found for the same ID"  # TODO: Throw error
                    competency_to_update = existing_competency[0]
                    embedings = generate_embeddings_openai(competency.description if competency.description else competency.title)
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

        # Recluster once after all competencies are saved
        self.recluster_with_new_competencies(competency=competencies[0], course_id=course_id)

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

    def recluster_with_new_competencies(self, competency: Competency, course_id: int):
        # Get competencies and exercise embeddings
        competencies = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "course_id", course_id
        )

        if len(competencies) == 0: return

        exercises = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.EXERCISE.value, "course_id", course_id
        )

        if len(exercises) == 0: return

        if len(competencies) > len(exercises): return

        # Delete all cluster centers for new centers
        self.weaviate_client.delete_by_property(
            CollectionNames.SEMANTIC_CLUSTER.value, "course_id", course_id
        )

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
            cluster = {"cluster_id": uuid.uuid4(), "label_id": str(index), "course_id": course_id}
            self.weaviate_client.add_embeddings(
                CollectionNames.SEMANTIC_CLUSTER.value, centroids[index].tolist(), cluster
            )

        clusters = self.weaviate_client.get_all_embeddings(CollectionNames.SEMANTIC_CLUSTER.value)

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
            competency_id: int = competency["properties"]["competency_id"]
            similarity_score = similarity_matrix[comp_idx][cluster_idx]

            properties = {
                "competency_id": competency_id,
                "title": competency["properties"]["title"],
                "description": competency["properties"]["description"],
                "cluster_id": clusters[cluster_idx]["properties"]["cluster_id"],
                "cluster_similarity_score": float(similarity_score),
                "course_id": course_id,
            }
            self.weaviate_client.update_property_by_id(
                CollectionNames.COMPETENCY.value, competency["id"], properties
            )
        return

    def new_text_suggestion(
            self,
            exercise_description: str,
            course_id: int,
            top_k: int = 3,
    ) -> list[tuple[Competency, float]]:
        """Process a new text entry and associate it with existing clusters."""
        exercise_embedding = generate_embeddings_openai(exercise_description)
        clusters = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.SEMANTIC_CLUSTER.value, "course_id", course_id
        )

        if not clusters:
            logger.warning("No clusters found in database")
            return self.suggest_competencies_if_no_clusters(exercise_description, course_id)
        else:
            # There are clusters which also mean that there are competencies
            cluster_centers = [
                SemanticCluster(cluster_id=entry["properties"]["cluster_id"],
                               course_id=entry["properties"]["course_id"],
                               vector_embedding=entry["vector"]["default"])
                for entry in clusters
            ]
            similarities_with_indices: list[tuple[float, SemanticCluster]] =  [
                (compute_cosine_similarity(exercise_embedding, cluster.vector_embedding), cluster)
                for cluster in cluster_centers
            ]
            similarities_with_indices.sort(key=lambda x: x[0], reverse=True)  # Sort by similarity score descending

            top_k = top_k if top_k < len(similarities_with_indices) else len(similarities_with_indices)
            topk_competencies = []
            for similarity_score, best_medoid  in similarities_with_indices[:top_k]:
                competency = self.weaviate_client.get_embeddings_by_property(
                    CollectionNames.COMPETENCY.value,
                    "cluster_id",
                    best_medoid.cluster_id
                )
                if not competency:
                    raise ValueError("No competency found for cluster")
                best_competency = Competency(
                    id=competency[0]["properties"]["competency_id"],
                    title=competency[0]["properties"]["title"],
                    description=competency[0]["properties"]["description"],
                    course_id=competency[0]["properties"].get("course_id", "unknown"),
                )
                topk_competencies.append((best_competency, similarity_score))

            return topk_competencies

    def suggest_competencies_by_similarity(
        self, exercise_description: str, course_id: int, top_k: int = 3
    ) -> list[Competency]:
        """Suggest competencies based on embedding similarity without re-clustering.

        Args:
            exercise_description: Description of the exercise to find similar competencies for
            course_id: Course ID to filter competencies by
            top_k: Number of top similar competencies to return (default: 3)

        Returns:
            List of most similar competencies ordered by similarity score
        """
        top_competencies_with_similarity_scores = self.new_text_suggestion(exercise_description, course_id, top_k)
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
                embedding = self.save_exercise_to_weaviate(exercise)
                self.instructor_feedback_on_new_text(exercise, embedding)

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

    def instructor_feedback_on_new_text(
            self,
            new_exercise: ExerciseWithCompetencies,
            new_exercise_embedding: list[float],
    ):
        # If there are no competencies, then there is nothing to do
        if new_exercise.competencies == []: return
        self.update_cluster_for_competencies(new_exercise_embedding, new_exercise.competencies, is_removal=False, is_new_exercise=True)

    def instructor_feedback(
            self,
            updated_exercise: ExerciseWithCompetencies,
            updated_exercise_embedding: list[float],
            old_exercise,
    ):
        # If there are no competencies, then there is nothing to do
        if not updated_exercise.competencies: return

        old_exercise_with_competencies = ExerciseWithCompetencies(
            id=old_exercise["properties"]["exercise_id"],
            title=old_exercise["properties"]["title"],
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
            exercise_embedding: list[float],
            competency_ids: list[int],
            is_removal=False,
            is_new_exercise=False,
    ):
        """Helper function to update cluster centroids for a set of competencies."""
        if not competency_ids: return
        for comp_id in competency_ids:
            # Get the competency and its cluster
            competency_data = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.COMPETENCY.value, "competency_id", comp_id
            )
            if not competency_data:
                continue

            cluster_id = competency_data[0]["properties"]["cluster_id"]

            if not cluster_id:
                continue

            # Get current cluster centroid
            cluster_data = self.weaviate_client.get_embeddings_by_property(
                CollectionNames.SEMANTIC_CLUSTER.value, "cluster_id", cluster_id
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
                        current_centroid, cluster_size, np.array(exercise_embedding)
                    )
                    action = "removed"
                else:
                    continue
            else:
                cluster_size = cluster_size if is_new_exercise else (cluster_size - 1)
                updated_centroid = update_cluster_centroid_on_addition(
                    current_centroid, cluster_size, np.array(exercise_embedding)
                )
                action = "added"

            # Update the cluster centroid in Weaviate
            self.weaviate_client.update_property_by_id(
                CollectionNames.SEMANTIC_CLUSTER.value,
                cluster_data[0]["id"],
                cluster_data[0]["properties"],
                updated_centroid.tolist()
            )
            logger.info(f"Updated cluster centroid for {action} competency {comp_id}")

    def suggest_competency_relations(self, course_id: int) -> CompetencyRelationSuggestionResponse:
        """Suggest competency relations based on embedding similarity."""
        course_competencies = self.weaviate_client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "course_id", course_id)
        competencies: list[Competency] = [
            Competency(id=competency["properties"]["competency_id"],
                       title=competency["properties"]["title"],
                       description=competency["properties"]["description"],
                       course_id=competency["properties"]["course_id"])
            for competency in course_competencies
        ]
        descriptions: list[str] = [i.description for i in competencies]
        embeddings = np.array(
            [competency["vector"]["default"]
            for competency in course_competencies]
        )
        relationship_matrix = generate_competency_relationship(embeddings, descriptions)
        competencyRelationSuggestionResponse = CompetencyRelationSuggestionResponse(relations=[])
        for i in range(len(relationship_matrix)):
            for j in range(len(relationship_matrix)):
                relation_type: Optional[RelationType] = None
                if relationship_matrix[i][j] == "NONE": continue
                if relationship_matrix[i][j] == "MATCH": relation_type = RelationType.MATCH
                if relationship_matrix[i][j] == "REQUIRE": relation_type = RelationType.REQUIRES
                if relationship_matrix[i][j] == "EXTEND": relation_type = RelationType.EXTEND
                relation: CompetencyRelation = CompetencyRelation(tail_id=competencies[j].id, head_id=competencies[i].id, relation_type=relation_type)
                competencyRelationSuggestionResponse.relations.append(relation)
        return competencyRelationSuggestionResponse


    def suggest_competencies_if_no_clusters(
        self, exercise_description: str, course_id: int, similarity_threshold: float = 0.5
    ) -> list[tuple[Competency, float]]:
        """Suggest competencies based on embedding similarity without re-clustering.

        Args:
            exercise_description: Description of the exercise to find similar competencies for
            course_id: Course ID to filter competencies by
            similarity_threshold: Minimum similarity score to return a competency (default: 0.8)

        Returns:
            List of most similar competencies ordered by similarity score
        """
        exercise_embedding = generate_embeddings_openai(exercise_description)

        all_competencies = self.weaviate_client.get_embeddings_by_property(
            CollectionNames.COMPETENCY.value, "course_id", course_id
        )

        if not all_competencies:
            logger.warning("No competencies found in database")
            return []

        similarities = []
        for competency_data in all_competencies:
            competency_embedding = competency_data["vector"]["default"]
            similarity_score = compute_cosine_similarity(
                exercise_embedding, competency_embedding
            )

            competency = Competency(
                id=int(competency_data["properties"]["competency_id"]),
                title=competency_data["properties"]["title"],
                description=competency_data["properties"]["description"],
                course_id=int(competency_data["properties"]["course_id"]),
            )
            similarities.append((competency, similarity_score))

        similarities.sort(key=lambda x: x[1], reverse=True)
        top_competencies = [(comp, similarity_score) for comp, similarity_score in similarities if similarity_score >= similarity_threshold]

        logger.info(
            f"Found {len(top_competencies)} similar competencies for exercise description"
        )
        return top_competencies