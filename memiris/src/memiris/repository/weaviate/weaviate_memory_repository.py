from typing import Mapping, Optional, Sequence, Union
from uuid import UUID

from langfuse import observe
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.filters import Filter
from weaviate.collections.classes.grpc import QueryReference, TargetVectors
from weaviate.util import _WeaviateUUIDInt

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

    @observe(name="weaviate.memory_repository.save")
    def save(self, tenant: str, entity: Memory) -> Memory:
        """Save a Memory entity to Weaviate."""

        properties: dict[str, Union[str, bool]] = {
            "title": entity.title,
            "content": entity.content,
            "slept_on": entity.slept_on,
            "deleted": entity.deleted,
        }

        if entity.id and (
            isinstance(entity.id, _WeaviateUUIDInt) or self.find(tenant, entity.id)
        ):
            operation = self.collection.with_tenant(tenant).data.update  # type: ignore
        else:
            operation = self.collection.with_tenant(tenant).data.insert  # type: ignore

        result = operation(properties=properties, uuid=entity.id, vector=entity.vectors)  # type: ignore

        if not entity.id:
            entity.id = result

        WeaviateBidirectionalLinkHelper.update_links(
            entity.id,  # type: ignore
            entity.learnings,
            "learnings",
            "memories",
            self.memory_collection.with_tenant(tenant),
            self.learning_collection.with_tenant(tenant),
        )

        return entity

    @observe(name="weaviate.memory_repository.find")
    def find(self, tenant: str, entity_id: UUID) -> Optional[Memory]:
        """Find a Memory by its ID."""
        try:
            if not self.collection.tenants.exists(tenant):
                return None

            result = self.collection.with_tenant(tenant).query.fetch_object_by_id(
                uuid=entity_id,
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result:
                return None

            # Create Memory object
            return self.object_to_memory(result)
        except Exception as e:
            raise ValueError(f"Error retrieving Memory with id {entity_id}") from e

    @observe(name="weaviate.memory_repository.all")
    def all(self, tenant: str, include_deleted: bool = False) -> list[Memory]:
        """Get all Memory objects."""
        try:
            if not self.collection.tenants.exists(tenant):
                return []

            result = self.collection.with_tenant(tenant).query.fetch_objects(
                filters=(
                    Filter.by_property("deleted").equal(False)
                    if not include_deleted
                    else None
                ),
                limit=10000,
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result:
                return []

            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error retrieving all Memory objects") from e

    @observe(name="weaviate.memory_repository.delete")
    def delete(self, tenant: str, entity_id: UUID) -> None:
        """Delete a Memory by its ID."""
        try:
            if self.collection.tenants.exists(tenant):
                self.collection.with_tenant(tenant).data.delete_by_id(entity_id)
        except Exception as e:
            raise ValueError(f"Error deleting Memory with id {entity_id}") from e

    @observe(name="weaviate.memory_repository.search")
    def search(
        self, tenant: str, vector_name: str, vector: Sequence[float], count: int
    ) -> list[Memory]:
        try:
            if not self.collection.tenants.exists(tenant):
                return []

            # Use hybrid search to combine vector search with filter for non-deleted memories
            result = self.collection.with_tenant(tenant).query.hybrid(
                query=None,
                vector=vector,
                target_vector=vector_name,
                filters=Filter.by_property("deleted").equal(False),
                limit=count,
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result:
                return []

            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error searching for Memory objects") from e

    @observe(name="weaviate.memory_repository.search_multi")
    def search_multi(
        self, tenant: str, vectors: Mapping[str, Sequence[float]], count: int
    ) -> list[Memory]:
        if not vectors:
            return []
        try:
            if not self.collection.tenants.exists(tenant):
                return []

            vectors = {
                vector_name: vector for vector_name, vector in vectors.items() if vector
            }
            # Use hybrid search with filter for non-deleted memories
            result = self.collection.with_tenant(tenant).query.hybrid(
                query=None,
                vector=vectors,
                target_vector=TargetVectors.minimum(list(vectors.keys())),
                filters=Filter.by_property("deleted").equal(False),
                limit=count,
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result:
                return []

            # Create Memory objects
            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error searching for Memory objects") from e

    @observe(name="weaviate.memory_repository.find_unslept_memories")
    def find_unslept_memories(self, tenant: str) -> list[Memory]:
        try:
            if not self.collection.tenants.exists(tenant):
                return []

            # Combine filters for both unslept AND not deleted memories
            result = self.collection.with_tenant(tenant).query.fetch_objects(
                filters=Filter.by_property("slept_on").equal(False)
                & Filter.by_property("deleted").equal(False),
                limit=10000,
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result:
                return []

            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError("Error retrieving unslept Memory objects") from e

    @observe(name="weaviate.memory_repository.find_by_ids")
    def find_by_ids(self, tenant: str, ids: Sequence[UUID]) -> Sequence[Memory]:
        """
        Retrieve multiple memory objects by their IDs in a single batch operation.

        Args:
            tenant: The tenant identifier
            ids: List of memory IDs to retrieve

        Returns:
            List of Memory objects that match the provided IDs
        """
        if not ids:
            return []

        try:
            if not self.collection.tenants.exists(tenant):
                return []

            # Convert UUIDs to strings for the filter
            id_strings = [str(uid) for uid in ids]

            # Use proper filter syntax with Weaviate's filter classes
            result = self.collection.with_tenant(tenant).query.fetch_objects(
                filters=Filter.by_id().contains_any(id_strings),
                limit=len(ids),
                include_vector=True,
                return_references=[
                    QueryReference(link_on="learnings"),
                    QueryReference(link_on="connections"),
                ],
            )

            if not result or not result.objects:
                return []

            # Create Learning objects from the results
            return [self.object_to_memory(item) for item in result.objects]
        except Exception as e:
            raise ValueError(f"Error retrieving Memory objects by IDs: {e}") from e

    def find_all_tenants(self) -> list[str]:
        """Find all tenants in the Memory collection."""
        return list(self.memory_collection.tenants.get().keys())
