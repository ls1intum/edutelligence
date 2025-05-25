from typing import Mapping, Sequence
from uuid import UUID

from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.grpc import QueryReference, TargetVectors

from memiris.domain.memory import Memory
from memiris.repository.memory_repository import MemoryRepository
from memiris.repository.weaviate._weaviate_base_repository import (
    _WeaviateBaseRepository,
)
from memiris.repository.weaviate.weaviate_bidirectional_link_helper import (
    WeaviateBidirectionalLinkHelper,
)


class WeaviateMemoryRepository(MemoryRepository, _WeaviateBaseRepository):
    """
    WeaviateMemoryRepository is a concrete implementation of the MemoryRepository for Weaviate.
    """

    collection: Collection

    def __init__(self, client: WeaviateClient):
        """Initialize repository with Weaviate client and optional learning repository."""
        super().__init__(client)
        self.collection = self.memory_collection

    def save(self, tenant: str, entity: Memory) -> Memory:
        """Save a Memory entity to Weaviate."""

        properties = {"title": entity.title, "content": entity.content}

        if not entity.id:
            operation = self.collection.with_tenant(tenant).data.insert
        else:
            operation = self.collection.with_tenant(tenant).data.update  # type: ignore

        result = operation(properties=properties, uuid=entity.id, vector=entity.vectors)

        if not entity.id:
            entity.id = result

        if entity.id:
            WeaviateBidirectionalLinkHelper.update_links(
                entity.id,
                entity.learnings,
                "learnings",
                "memories",
                self.memory_collection.with_tenant(tenant),
                self.learning_collection.with_tenant(tenant),
            )
        else:
            WeaviateBidirectionalLinkHelper.add_links(
                entity.id,
                entity.learnings,
                "learnings",
                "memories",
                self.memory_collection.with_tenant(tenant),
                self.learning_collection.with_tenant(tenant),
            )

        return entity

    def find(self, tenant: str, entity_id: UUID) -> Memory:
        """Find a Memory by its ID."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_object_by_id(
                uuid=entity_id,
                include_vector=True,
                return_references=QueryReference(link_on="learnings"),
            )

            if not result:
                raise ValueError(f"Learning with id {entity_id} not found")

            # Create Memory object
            return self.object_to_memory(result)
        except Exception as e:
            raise ValueError(f"Error retrieving Memory with id {entity_id}") from e

    def all(self, tenant: str) -> list[Memory]:
        """Get all Memory objects."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_objects()

            if not result:
                return []

            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error retrieving all Memory objects") from e

    def delete(self, tenant: str, entity_id: UUID) -> None:
        """Delete a Memory by its ID."""
        try:
            self.collection.with_tenant(tenant).data.delete_by_id(entity_id)
        except Exception as e:
            raise ValueError(f"Error deleting Memory with id {entity_id}") from e

    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> list[Memory]:
        try:
            result = self.collection.with_tenant(tenant).query.near_vector(
                near_vector=vector,
                target_vector=vector_name,
                limit=count,
                include_vector=True,
                return_references=QueryReference(link_on="learnings"),
            )

            if not result:
                return []

            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error searching for Memory objects") from e

    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Memory]:
        try:
            vectors = {
                vector_name: vector for vector_name, vector in vectors.items() if vector
            }
            result = self.collection.with_tenant(tenant).query.near_vector(
                near_vector=vectors,
                target_vector=TargetVectors.minimum(list(vectors.keys())),
                limit=count,
                include_vector=True,
                return_references=QueryReference(link_on="learnings"),
            )

            if not result:
                return []

            # Create Memory objects
            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error searching for Memory objects") from e
