from typing import List, Optional, Sequence
from uuid import UUID

from langfuse import observe
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.filters import Filter
from weaviate.collections.classes.grpc import QueryReference
from weaviate.util import _WeaviateUUIDInt

from memiris.domain.memory_connection import ConnectionType, MemoryConnection
from memiris.repository.memory_connection_repository import MemoryConnectionRepository
from memiris.repository.weaviate._weaviate_base_repository import (
    _WeaviateBaseRepository,
)
from memiris.repository.weaviate.weaviate_bidirectional_link_helper import (
    WeaviateBidirectionalLinkHelper,
)


class WeaviateMemoryConnectionRepository(
    MemoryConnectionRepository, _WeaviateBaseRepository
):
    """
    WeaviateMemoryConnectionRepository is a concrete implementation of the MemoryConnectionRepository for Weaviate.
    """

    collection: Collection

    def __init__(self, client: WeaviateClient):
        """Initialize repository with Weaviate client."""
        super().__init__(client)
        self.collection = self.memory_connection_collection

    @observe(name="weaviate.memory_connection_repository.save")
    def save(self, tenant: str, entity: MemoryConnection) -> MemoryConnection:
        """Save a MemoryConnection entity to Weaviate."""

        # Convert enum type to string for storage
        properties = {
            "connection_type": entity.connection_type.value,
            "description": entity.description,
            "weight": entity.weight,
        }

        if entity.id and (
            isinstance(entity.id, _WeaviateUUIDInt) or self.find(tenant, entity.id)
        ):
            operation = self.collection.with_tenant(tenant).data.update  # type: ignore
        else:
            operation = self.collection.with_tenant(tenant).data.insert  # type: ignore

        result = operation(properties=properties, uuid=entity.id)  # type: ignore

        if not entity.id:
            entity.id = result

        # Update bidirectional links between memories and this connection
        if entity.memories:
            WeaviateBidirectionalLinkHelper.update_links(
                entity.id,  # type: ignore
                entity.memories,
                "connected_memories",
                "connections",
                self.memory_connection_collection.with_tenant(tenant),
                self.memory_collection.with_tenant(tenant),
            )

        return entity

    @observe(name="weaviate.memory_connection_repository.find")
    def find(self, tenant: str, entity_id: UUID) -> Optional[MemoryConnection]:
        """Find a MemoryConnection by its ID."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_object_by_id(
                uuid=entity_id,
                return_references=[QueryReference(link_on="connected_memories")],
            )

            if not result:
                return None

            # Create MemoryConnection object
            return self.object_to_memory_connection(result)
        except Exception as e:
            raise ValueError(
                f"Error retrieving MemoryConnection with id {entity_id}"
            ) from e

    @observe(name="weaviate.memory_connection_repository.all")
    def all(self, tenant: str) -> List[MemoryConnection]:
        """Get all MemoryConnection objects."""
        try:
            if not self.collection.tenants.exists(tenant):
                return []

            result = self.collection.with_tenant(tenant).query.fetch_objects(
                limit=10000,
                return_references=[QueryReference(link_on="connected_memories")],
            )

            if not result:
                return []

            return [self.object_to_memory_connection(item) for item in result.objects]
        except Exception as e:
            print(e)
            raise ValueError("Error retrieving all MemoryConnection objects") from e

    @observe(name="weaviate.memory_connection_repository.delete")
    def delete(self, tenant: str, entity_id: UUID) -> None:
        """Delete a MemoryConnection by its ID."""
        try:
            self.collection.with_tenant(tenant).data.delete_by_id(entity_id)
        except Exception as e:
            raise ValueError(
                f"Error deleting MemoryConnection with id {entity_id}"
            ) from e

    @observe(name="weaviate.memory_connection_repository.find_by_connection_type")
    def find_by_connection_type(
        self, tenant: str, connection_type: str
    ) -> List[MemoryConnection]:
        """
        Find all memory connections of a specific type.

        Args:
            tenant: The tenant identifier
            connection_type: Type of connection to filter by

        Returns:
            List of MemoryConnection objects of the specified type
        """
        try:
            # Validate that the connection type is valid
            try:
                ConnectionType(connection_type)
            except ValueError as e:
                raise ValueError(f"Invalid connection type: {connection_type}") from e

            # Query connections of the specified type
            result = self.collection.with_tenant(tenant).query.fetch_objects(
                filters=Filter.by_property("connection_type").equal(connection_type),
                return_references=[QueryReference(link_on="connected_memories")],
            )

            if not result:
                return []

            return [self.object_to_memory_connection(item) for item in result.objects]
        except Exception as e:
            raise ValueError(
                f"Error finding connections of type {connection_type}: {e}"
            ) from e

    @observe(name="weaviate.memory_connection_repository.find_by_ids")
    def find_by_ids(
        self, tenant: str, ids: Sequence[UUID]
    ) -> Sequence[MemoryConnection]:
        """
        Retrieve multiple memory connection objects by their IDs in a single batch operation.

        Args:
            tenant: The tenant identifier
            ids: List of memory connection IDs to retrieve

        Returns:
            List of MemoryConnection objects that match the provided IDs
        """
        if not ids:
            return []

        try:
            # Convert UUIDs to strings for the filter
            id_strings = [str(uid) for uid in ids]

            # Use proper filter syntax with Weaviate's filter classes
            result = self.collection.with_tenant(tenant).query.fetch_objects(
                filters=Filter.by_id().contains_any(id_strings),
                limit=len(ids),
                return_references=[
                    QueryReference(link_on="connected_memories"),
                ],
            )

            if not result or not result.objects:
                return []

            # Create Learning objects from the results
            return [self.object_to_memory_connection(item) for item in result.objects]
        except Exception as e:
            raise ValueError(
                f"Error retrieving MemoryConnection objects by IDs: {e}"
            ) from e
