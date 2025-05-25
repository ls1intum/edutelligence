from typing import Mapping, Sequence
from uuid import UUID

from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.grpc import QueryReference, TargetVectors

from memiris.domain.learning import Learning
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.weaviate._weaviate_base_repository import (
    _WeaviateBaseRepository,
)


class WeaviateLearningRepository(LearningRepository, _WeaviateBaseRepository):
    """
    WeaviateLearningRepository is a concrete implementation of the LearningRepository for Weaviate.
    """

    collection: Collection

    def __init__(self, client: WeaviateClient):
        """Initialize repository with Weaviate client and optional learning repository."""
        super().__init__(client)
        self.collection = self.learning_collection

    def save(self, tenant: str, entity: Learning) -> Learning:
        """Save a Learning entity to Weaviate."""

        properties = {
            "title": entity.title,
            "content": entity.content,
            "reference": entity.reference,
        }

        if not entity.id:
            operation = self.collection.with_tenant(tenant).data.insert
        else:
            operation = self.collection.with_tenant(tenant).data.update  # type: ignore

        result = operation(properties=properties, uuid=entity.id, vector=entity.vectors)

        if not entity.id:
            entity.id = result

        return entity

    def find(self, tenant: str, entity_id: UUID) -> Learning:
        """Find a Learning by its ID."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_object_by_id(
                uuid=entity_id,
                include_vector=True,
                return_references=QueryReference(link_on="memories"),
            )

            if not result:
                raise ValueError(f"Learning with id {entity_id} not found")

            return self.object_to_learning(result)
        except Exception as e:
            raise ValueError(f"Error retrieving Learning with id {entity_id}") from e

    def all(self, tenant: str) -> list[Learning]:
        """Get all Learning objects."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_objects(
                return_references=QueryReference(link_on="memories"),
            )

            if not result:
                return []

            return [self.object_to_learning(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error retrieving all Learning objects") from e

    def delete(self, tenant: str, entity_id: UUID) -> None:
        """Delete a Learning by its ID."""
        try:
            self.collection.with_tenant(tenant).data.delete_by_id(entity_id)
        except Exception as e:
            raise ValueError(f"Error deleting Learning with id {entity_id}") from e

    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> list[Learning]:
        try:
            result = self.collection.with_tenant(tenant).query.near_vector(
                near_vector=vector,
                target_vector=vector_name,
                limit=count,
                include_vector=True,
                return_references=QueryReference(link_on="memories"),
            )

            if not result:
                return []

            # Create Learning objects
            return [self.object_to_learning(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error finding similar Learning objects") from e

    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Learning]:
        try:
            vectors = {
                vector_name: vector for vector_name, vector in vectors.items() if vector
            }
            result = self.collection.with_tenant(tenant).query.near_vector(
                near_vector=vectors,
                target_vector=TargetVectors.minimum(list(vectors.keys())),
                limit=count,
                return_references=QueryReference(link_on="memories"),
            )

            if not result:
                return []

            # Create Learning objects
            return [self.object_to_learning(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error searching for Learning objects") from e
