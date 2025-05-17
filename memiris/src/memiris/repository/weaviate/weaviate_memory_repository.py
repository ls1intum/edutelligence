from typing import List, Mapping, Sequence
from uuid import UUID

from weaviate import WeaviateClient
from weaviate.classes.config import Configure, DataType, Property, ReferenceProperty
from weaviate.collections import Collection
from weaviate.collections.classes.config import VectorDistances
from weaviate.collections.classes.grpc import QueryReference, TargetVectors

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.repository.learning_repository import LearningRepository
from memiris.repository.memory_repository import MemoryRepository


class WeaviateMemoryRepository(MemoryRepository):
    """
    WeaviateMemoryRepository is a concrete implementation of the MemoryRepository for Weaviate.
    """

    client: WeaviateClient
    learning_repository: LearningRepository
    collection_name: str
    collection: Collection
    _vector_count = 5

    def __init__(self, client: WeaviateClient, learning_repository: LearningRepository):
        """Initialize repository with Weaviate client and optional learning repository."""
        self.client = client
        self.learning_repository = learning_repository
        self.collection_name = "Memory"
        self._ensure_schema()
        self.collection = self.client.collections.get(self.collection_name)

    def _ensure_schema(self) -> None:
        """Ensure Memory collection schema exists or create it."""
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
                description="A memory object represents 1+ processed learning objects.",
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
                ],
                references=[
                    ReferenceProperty(
                        name="learnings",
                        target_collection="Learning",
                        description="Source learning objects",
                    ),
                ],
            )

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
            # Update references - first remove all existing references
            try:
                existing_refs = (
                    self.collection.with_tenant(tenant)
                    .query.fetch_object_by_id(
                        uuid=str(entity.id),
                        return_references=QueryReference(
                            link_on="learnings", return_properties=["id"]
                        ),
                    )
                    .references
                )

                if existing_refs and "learnings" in existing_refs:
                    for ref in existing_refs["learnings"].objects:
                        self.collection.data.reference_delete(
                            from_uuid=str(entity.id),
                            from_property="learnings",
                            to=ref.uuid,
                        )
            except Exception:
                print(
                    f"Error while removing existing references for Memory {entity.id}"
                )

        # Add references to learnings
        if entity.learnings:
            for learning in entity.learnings:
                self.collection.with_tenant(tenant).data.reference_add(
                    from_uuid=str(entity.id),
                    from_property="learnings",
                    to=learning.id,  # type: ignore
                )

        return entity

    def find(self, tenant: str, entity_id: UUID) -> Memory:
        """Find a Memory by its ID."""
        try:
            result = self.collection.with_tenant(tenant).query.fetch_object_by_id(
                uuid=entity_id,
                include_vector=True,
                return_references=QueryReference(
                    link_on="learnings", return_properties=["id"]
                ),
            )

            if not result:
                raise ValueError(f"Learning with id {entity_id} not found")

            # Resolve Learning references
            learnings = self._get_learnings(tenant, result.references)

            # Create Memory object
            return Memory(
                uid=result.uuid,
                title=str(result.properties["title"]),
                content=str(result.properties["content"]),
                learnings=learnings,
                vectors=result.vector,  # type: ignore
            )
        except Exception as e:
            raise ValueError(f"Error retrieving Memory with id {entity_id}") from e

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
                return_references=QueryReference(
                    link_on="learnings", return_properties=["id"]
                ),
            )

            if not result:
                return []

            return [
                Memory(
                    uid=item.uuid,
                    title=str(item.properties["title"]),
                    content=str(item.properties["content"]),
                    learnings=self._get_learnings(tenant, item.references),
                    vectors=item.vector,  # type: ignore
                )
                for item in result.objects
            ]
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
                return_references=QueryReference(
                    link_on="learnings", return_properties=["id"]
                ),
            )

            if not result:
                return []

            # Create Memory objects
            return [
                Memory(
                    uid=item.uuid,
                    title=str(item.properties["title"]),
                    content=str(item.properties["content"]),
                    learnings=self._get_learnings(tenant, item.references),
                    vectors=item.vector,  # type: ignore
                )
                for item in result.objects
            ]
        except Exception as e:
            raise ValueError("Error searching for Memory objects") from e

    def _get_learnings(self, tenant: str, refs) -> List[Learning]:
        learnings = []
        if refs and "learnings" in refs:
            learning_refs = refs["learnings"]

            if self.learning_repository:
                for ref in learning_refs.objects:
                    learning_id = ref.uuid
                    learning = self.learning_repository.find(tenant, learning_id)
                    learnings.append(learning)
        return learnings
