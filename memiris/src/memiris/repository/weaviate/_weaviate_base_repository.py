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


class _WeaviateBaseRepository(ABC):
    """
    Base class for Weaviate repositories.
    This class is intended to be inherited by specific repositories for domain entities.
    It provides common functionality for dealing with Weaviate.
    """

    client: WeaviateClient
    learning_collection_name: str = "Learning"
    memory_collection_name: str = "Memory"
    _vector_count: int = 5
    learning_collection: Collection
    memory_collection: Collection
    memory_learning_reference_name: str = "learnings"
    learning_memory_reference_name: str = "memories"

    def __init__(self, client: WeaviateClient):
        """
        Initialize the repository with all necessary components.
        """
        self.client = client
        self._ensure_learning_schema()
        self._ensure_memory_schema()
        self._ensure_bidirectional_links()
        self.learning_collection = client.collections.get("Learning")
        self.memory_collection = client.collections.get("Memory")

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

    def _ensure_bidirectional_links(self) -> None:
        """
        Ensure that bidirectional links are set up between Learning and Memory collections.
        """
        learning_collection = self.client.collections.get(self.learning_collection_name)
        memory_collection = self.client.collections.get(self.memory_collection_name)

        if not learning_collection.config.get().references:
            learning_collection.config.add_reference(
                ReferenceProperty(
                    name=self.learning_memory_reference_name,
                    target_collection=self.memory_collection_name,
                    description="Memories associated with this learning object",
                )
            )

        if not memory_collection.config.get().references:
            memory_collection.config.add_reference(
                ReferenceProperty(
                    name=self.memory_learning_reference_name,
                    target_collection=self.learning_collection_name,
                    description="Learnings associated with this memory object",
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
            vectors=obj.vector if obj.vector else {},  # type: ignore
            slept_on=obj.properties.get("slept_on", False),
        )
