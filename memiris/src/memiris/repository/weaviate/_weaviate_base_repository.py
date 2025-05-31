from abc import ABC

from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    Property,
    ReferenceProperty,
    VectorDistances,
)
from weaviate.collections.classes.internal import Object, ObjectSingleReturn

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.domain.memory_connection import ConnectionType, MemoryConnection


class _WeaviateBaseRepository(ABC):
    """
    Base class for Weaviate repositories.
    This class is intended to be inherited by specific repositories for domain entities.
    It provides common functionality for dealing with Weaviate.
    """

    client: WeaviateClient
    learning_collection_name: str = "Learning"
    memory_collection_name: str = "Memory"
    memory_connection_collection_name: str = "MemoryConnection"
    _vector_count: int = 5
    learning_collection: Collection
    memory_collection: Collection
    memory_connection_collection: Collection
    memory_learning_reference_name: str = "learnings"
    learning_memory_reference_name: str = "memories"
    memory_connection_memory_reference_name: str = "connected_memories"
    memory_connection_reference_name: str = "connections"

    def __init__(self, client: WeaviateClient):
        """
        Initialize the repository with all necessary components.
        """
        self.client = client
        self._ensure_learning_schema()
        self._ensure_memory_schema()
        self._ensure_memory_connection_schema()
        self._ensure_bidirectional_links()
        self.learning_collection = client.collections.get("Learning")
        self.memory_collection = client.collections.get("Memory")
        self.memory_connection_collection = client.collections.get("MemoryConnection")

    def _ensure_learning_schema(self) -> None:
        vector_config = [
            Configure.NamedVectors.none(
                f"vector_{i}",
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE,
                ),
            )
            for i in range(self._vector_count)
        ]

        if not self.client.collections.exists(self.learning_collection_name):
            self.client.collections.create(
                name=self.learning_collection_name,
                description="(v0.2) A learning object represents a piece of "
                "information that has been learned from a source.",
                vectorizer_config=vector_config,
                multi_tenancy_config=Configure.multi_tenancy(
                    enabled=True, auto_tenant_creation=True, auto_tenant_activation=True
                ),
                properties=[
                    Property(
                        name="title",
                        data_type=DataType.TEXT,
                        description="Learning title",
                    ),
                    Property(
                        name="content",
                        data_type=DataType.TEXT,
                        description="Learning content",
                    ),
                    Property(
                        name="reference",
                        data_type=DataType.TEXT,
                        description="Learning reference",
                    ),
                ],
            )

    def _ensure_memory_schema(self) -> None:
        vector_config = [
            Configure.NamedVectors.none(
                f"vector_{i}",
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE,
                ),
            )
            for i in range(self._vector_count)
        ]

        if not self.client.collections.exists(self.memory_collection_name):
            self.client.collections.create(
                name=self.memory_collection_name,
                description="(v0.2) A memory object represents 1+ processed learning objects.",
                vectorizer_config=vector_config,
                multi_tenancy_config=Configure.multi_tenancy(
                    enabled=True, auto_tenant_creation=True, auto_tenant_activation=True
                ),
                properties=[
                    Property(
                        name="title",
                        data_type=DataType.TEXT,
                        description="Memory title",
                    ),
                    Property(
                        name="content",
                        data_type=DataType.TEXT,
                        description="Memory content",
                    ),
                    Property(
                        name="slept_on",
                        data_type=DataType.BOOL,
                        description="Indicates if the memory has been slept on",
                    ),
                    Property(
                        name="deleted",
                        data_type=DataType.BOOL,
                        description="Indicates if the memory has been deleted",
                    ),
                ],
            )

    def _ensure_memory_connection_schema(self) -> None:
        """
        Ensure that the MemoryConnection schema exists in Weaviate.
        """
        if not self.client.collections.exists(self.memory_connection_collection_name):
            self.client.collections.create(
                name=self.memory_connection_collection_name,
                description="(v0.1) A connection between two or more memory "
                "objects that represents their relationship.",
                multi_tenancy_config=Configure.multi_tenancy(
                    enabled=True, auto_tenant_creation=True, auto_tenant_activation=True
                ),
                properties=[
                    Property(
                        name="connection_type",
                        data_type=DataType.TEXT,
                        description="Type of connection between memories "
                        "(e.g., RELATED, ELABORATES, CONTRADICTS, etc.)",
                    ),
                    Property(
                        name="description",
                        data_type=DataType.TEXT,
                        description="Description of the connection",
                    ),
                    Property(
                        name="confidence",
                        data_type=DataType.NUMBER,
                        description="Confidence score for this connection (0.0 - 1.0)",
                    ),
                ],
            )

    def _ensure_bidirectional_links(self) -> None:
        """
        Ensure that bidirectional links are set up between collections:
        - Learning <-> Memory
        - MemoryConnection <-> Memory
        """
        learning_collection = self.client.collections.get(self.learning_collection_name)
        memory_collection = self.client.collections.get(self.memory_collection_name)
        memory_connection_collection = self.client.collections.get(
            self.memory_connection_collection_name
        )
        existing_memory_refs = memory_collection.config.get().references

        # Set up Learning <-> Memory bidirectional links
        # Learning -> Memory
        if not learning_collection.config.get().references:
            learning_collection.config.add_reference(
                ReferenceProperty(
                    name=self.learning_memory_reference_name,
                    target_collection=self.memory_collection_name,
                    description="Memories associated with this learning object",
                )
            )

        # Memory -> Learning
        if not existing_memory_refs or not any(
            ref.name == self.memory_learning_reference_name
            for ref in existing_memory_refs
        ):
            memory_collection.config.add_reference(
                ReferenceProperty(
                    name=self.memory_learning_reference_name,
                    target_collection=self.learning_collection_name,
                    description="Learnings associated with this memory object",
                )
            )

        # Set up MemoryConnection <-> Memory bidirectional links
        # Memory -> MemoryConnection
        if not existing_memory_refs or not any(
            ref.name == self.memory_connection_reference_name
            for ref in existing_memory_refs
        ):
            memory_collection.config.add_reference(
                ReferenceProperty(
                    name=self.memory_connection_reference_name,
                    target_collection=self.memory_connection_collection_name,
                    description="Connections this memory is part of",
                )
            )

        # MemoryConnection -> Memory
        if not memory_connection_collection.config.get().references:
            memory_connection_collection.config.add_reference(
                ReferenceProperty(
                    name=self.memory_connection_memory_reference_name,
                    target_collection=self.memory_collection_name,
                    description="Memories that are part of this connection",
                )
            )

    @staticmethod
    def object_to_learning(obj: Object | ObjectSingleReturn) -> Learning:
        """
        Convert a Weaviate Object to a Learning domain object.
        """
        return Learning(
            uid=obj.uuid,
            title=str(obj.properties.get("title", "")),
            content=str(obj.properties.get("content", "")),
            reference=str(obj.properties.get("reference", "")),
            memories=(
                [ref.uuid for ref in obj.references["memories"].objects]
                if obj.references
                and "memories" in obj.references
                and obj.references["memories"].objects
                else []
            ),
            vectors=obj.vector if obj.vector else {},  # type: ignore
        )

    @staticmethod
    def object_to_memory(obj: Object | ObjectSingleReturn) -> Memory:
        """
        Convert a Weaviate Object to a Memory domain object.
        """
        return Memory(
            uid=obj.uuid,
            title=str(obj.properties["title"]),
            content=str(obj.properties["content"]),
            learnings=(
                [ref.uuid for ref in obj.references["learnings"].objects]
                if obj.references
                and "learnings" in obj.references
                and obj.references["learnings"].objects
                else []
            ),
            connections=(
                [ref.uuid for ref in obj.references["connections"].objects]
                if obj.references
                and "connections" in obj.references
                and obj.references["connections"].objects
                else []
            ),
            vectors=obj.vector if obj.vector else {},  # type: ignore
            slept_on=obj.properties.get("slept_on", False),
            deleted=obj.properties.get("deleted", False),
        )

    @staticmethod
    def object_to_memory_connection(
        obj: Object | ObjectSingleReturn,
    ) -> MemoryConnection:
        """
        Convert a Weaviate Object to a MemoryConnection domain object.
        """
        # Convert string connection type to enum
        connection_type_str = str(obj.properties.get("connection_type", "related"))
        try:
            connection_type = ConnectionType(connection_type_str)
        except ValueError:
            # If the connection type is invalid, use RELATED as default
            connection_type = ConnectionType.RELATED

        return MemoryConnection(
            uid=obj.uuid,
            connection_type=connection_type,
            memories=(
                [ref.uuid for ref in obj.references["connected_memories"].objects]
                if obj.references
                and "connected_memories" in obj.references
                and obj.references["connected_memories"].objects
                else []
            ),
            description=str(obj.properties.get("description", "")),
            confidence=float(obj.properties.get("confidence", 1.0)),
        )
