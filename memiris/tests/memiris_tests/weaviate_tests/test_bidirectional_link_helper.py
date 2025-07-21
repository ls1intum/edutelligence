from uuid import uuid4

import pytest
from memiris_tests.weaviate_tests.test_setup import WeaviateTest
from weaviate.client import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import DataType, Property, ReferenceProperty
from weaviate.collections.classes.grpc import QueryReference

from memiris.repository.weaviate.weaviate_bidirectional_link_helper import (
    WeaviateBidirectionalLinkHelper,
)


class TestEntity:
    """Test entity class that conforms to EntityWithId protocol."""

    def __init__(self, uid=None):
        self.id = uid if uid else uuid4()


class TestWeaviateBidirectionalLinkHelper(WeaviateTest):
    """
    Tests for WeaviateBidirectionalLinkHelper class.
    It uses testcontainers to run a Weaviate instance in a Docker container.
    """

    @pytest.fixture(scope="function")
    def weaviate_collections(self, weaviate_client: WeaviateClient):
        """Create test collections for testing bidirectional links."""
        # Clean up any existing test collections
        try:
            weaviate_client.collections.delete("TestCollection1")
        except Exception:
            pass
        try:
            weaviate_client.collections.delete("TestCollection2")
        except Exception:
            pass

        # First create both collections without references
        collection1 = weaviate_client.collections.create(
            name="TestCollection1",
            properties=[
                Property(
                    name="test_property",
                    data_type=DataType.TEXT,
                    description="A test property",
                ),
            ],
        )

        collection2 = weaviate_client.collections.create(
            name="TestCollection2",
            properties=[
                Property(
                    name="test_property",
                    data_type=DataType.TEXT,
                    description="A test property",
                ),
            ],
        )

        # Now add references after both collections exist
        collection1.config.add_reference(
            ReferenceProperty(
                name="link_to_collection2",
                target_collection="TestCollection2",
                description="Link to TestCollection2 entities",
            )
        )

        collection2.config.add_reference(
            ReferenceProperty(
                name="link_to_collection1",
                target_collection="TestCollection1",
                description="Link to TestCollection1 entities",
            )
        )

        # Get the updated collections
        collection1 = weaviate_client.collections.get("TestCollection1")
        collection2 = weaviate_client.collections.get("TestCollection2")

        return collection1, collection2

    @pytest.fixture(scope="function")
    def test_entities(
        self, weaviate_collections: tuple[Collection, Collection]
    ) -> tuple[TestEntity, TestEntity]:
        """Create test entities in both collections."""
        collection1, collection2 = weaviate_collections

        # Create test entity in collection1
        entity1_id = uuid4()
        collection1.data.insert(
            properties={"test_property": "Test property value for entity1"},
            uuid=entity1_id,
        )
        entity1 = TestEntity(entity1_id)

        # Create test entity in collection2
        entity2_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity2"},
            uuid=entity2_id,
        )
        entity2 = TestEntity(entity2_id)

        return entity1, entity2

    def test_add_link(
        self,
        weaviate_collections: tuple[Collection, Collection],
        test_entities: tuple[TestEntity, TestEntity],
    ):
        """Test adding a bidirectional link between two entities."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Add bidirectional link
        WeaviateBidirectionalLinkHelper.add_link(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        actual1 = collection1.query.fetch_object_by_id(
            entity1.id, return_references=QueryReference(link_on="link_to_collection2")
        )

        actual2 = collection2.query.fetch_object_by_id(
            entity2.id, return_references=QueryReference(link_on="link_to_collection1")
        )

        assert len(actual1.references) == 1
        assert len(actual2.references) == 1
        assert "link_to_collection2" in actual1.references
        assert "link_to_collection1" in actual2.references
        assert any(
            ref.uuid == entity2.id
            for ref in actual1.references["link_to_collection2"].objects
        )
        assert any(
            ref.uuid == entity1.id
            for ref in actual2.references["link_to_collection1"].objects
        )

    def test_remove_link(self, weaviate_collections, test_entities):
        """Test removing a bidirectional link between two entities."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Add link first
        WeaviateBidirectionalLinkHelper.add_link(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Remove the link
        WeaviateBidirectionalLinkHelper.remove_link(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Verify the link no longer exists
        assert not WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

    def test_link_exists(self, weaviate_collections, test_entities):
        """Test checking if a bidirectional link exists between two entities."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Initially, no link should exist
        assert not WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Add link
        WeaviateBidirectionalLinkHelper.add_link(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Now link should exist
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

    def test_add_links(self, weaviate_collections, test_entities):
        """Test adding multiple bidirectional links from one entity to multiple entities."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Create additional entities in collection2
        entity3_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity3"},
            uuid=entity3_id,
        )
        entity3 = TestEntity(entity3_id)

        entity4_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity4"},
            uuid=entity4_id,
        )
        entity4 = TestEntity(entity4_id)

        # Add multiple links
        WeaviateBidirectionalLinkHelper.add_links(
            entity1.id,
            [entity2.id, entity3.id, entity4.id],
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Check all links exist
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity3.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity4.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

    def test_remove_links(self, weaviate_collections, test_entities):
        """Test removing multiple bidirectional links from one entity to multiple entities."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Create additional entities in collection2
        entity3_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity3"},
            uuid=entity3_id,
        )
        entity3 = TestEntity(entity3_id)

        entity4_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity4"},
            uuid=entity4_id,
        )
        entity4 = TestEntity(entity4_id)

        # Add multiple links first
        WeaviateBidirectionalLinkHelper.add_links(
            entity1.id,
            [entity2.id, entity3.id, entity4.id],
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Remove subset of links
        WeaviateBidirectionalLinkHelper.remove_links(
            entity1.id,
            [entity2.id, entity3.id],
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Check removed links don't exist
        assert not WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )
        assert not WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity3.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # But the non-removed link still exists
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity4.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

    def test_update_links(self, weaviate_collections, test_entities):
        """Test updating bidirectional links by removing existing ones and adding new ones."""
        collection1, collection2 = weaviate_collections
        entity1, entity2 = test_entities

        # Create additional entities in collection2
        entity3_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity3"},
            uuid=entity3_id,
        )
        entity3 = TestEntity(entity3_id)

        entity4_id = uuid4()
        collection2.data.insert(
            properties={"test_property": "Test property value for entity4"},
            uuid=entity4_id,
        )
        entity4 = TestEntity(entity4_id)

        # Add initial links
        WeaviateBidirectionalLinkHelper.add_links(
            entity1.id,
            [entity2.id, entity3.id],
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Update links (remove entity2, keep entity3, add entity4)
        WeaviateBidirectionalLinkHelper.update_links(
            entity1.id,
            [entity3.id, entity4.id],
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Check that entity2 link is removed
        assert not WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity2.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Check that entity3 link is still there
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity3.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )

        # Check that entity4 link is added
        assert WeaviateBidirectionalLinkHelper.link_exists(
            entity1.id,
            entity4.id,
            "link_to_collection2",
            "link_to_collection1",
            collection1,
            collection2,
        )
