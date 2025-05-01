from uuid import UUID

from weaviate import WeaviateClient
from weaviate.classes.config import DataType, Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances

from memiris.domain.learning import Learning
from memiris.repository.learning_repository import LearningRepository


class WeaviateLearningRepository(LearningRepository):
    """
    WeaviateLearningRepository is a concrete implementation of the LearningRepository for Weaviate.
    """

    client: WeaviateClient
    collection_name: str
    collection: Collection
    _vector_count = 5

    def __init__(self, client: WeaviateClient):
        """Initialize repository with Weaviate client and optional learning repository."""
        self.client = client
        self.collection_name = "Learning"
        self._ensure_schema()
        self.collection = self.client.collections.get(self.collection_name)

    def _ensure_schema(self) -> None:
        """Ensure Learning collection schema exists or create it."""
        vector_config = [
            Configure.NamedVectors.none(
                f"vector_{i}",
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE,
                ),
            )
            for i in range(self._vector_count)
        ]

        if not self.client.collections.exists(self.collection_name):
            self.client.collections.create(
                name=self.collection_name,
                description="A learning object represents a piece of information that has been learned from a source.",
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

    def save(self, tenant: str, entity: Learning) -> Learning:
        """Save a Learning entity to Weaviate."""

        properties = {"title": entity.title, "content": entity.content}

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
                uuid=entity_id, include_vector=False
            )

            if not result:
                raise ValueError(f"Learning with id {entity_id} not found")

            # Create Learning object
            return Learning(
                uid=result.uuid,
                title=str(result.properties["title"]),
                content=str(result.properties["content"]),
                reference=str(result.properties["reference"]),
            )
        except Exception as e:
            raise ValueError(f"Error retrieving Learning with id {entity_id}") from e

    def delete(self, tenant: str, entity_id: UUID) -> None:
        """Delete a Learning by its ID."""
        try:
            self.collection.with_tenant(tenant).data.delete_by_id(entity_id)
        except Exception as e:
            raise ValueError(f"Error deleting Learning with id {entity_id}") from e
