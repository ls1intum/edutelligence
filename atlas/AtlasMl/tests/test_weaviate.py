from unittest.mock import MagicMock, patch

import pytest
from weaviate.exceptions import WeaviateConnectionError

from atlasml.clients.weaviate import (
    CollectionNames,
    WeaviateClient,
    get_weaviate_client,
)


@pytest.fixture
def mock_weaviate():
    """Fixture to mock the Weaviate client and its dependencies."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_filter = MagicMock()

    # Set up the mock filter chain
    mock_filter.by_property.return_value.equal.return_value = mock_filter

    # Set up the mock collection
    mock_collection.data.insert.return_value = "test-uuid"
    mock_collection.iterator.return_value = [
        MagicMock(
            uuid="test-uuid-1",
            properties={"text": "test text", "name": "test name"},
            vector=[0.1, 0.2, 0.3],
        ),
        MagicMock(
            uuid="test-uuid-2",
            properties={"text": "test text 2", "name": "test name 2"},
            vector=[0.4, 0.5, 0.6],
        ),
    ]
    mock_collection.query.fetch_objects.return_value.objects = [
        MagicMock(
            uuid="test-uuid-1",
            properties={"text": "test text", "name": "test name"},
            vector=[0.1, 0.2, 0.3],
        )
    ]

    # Set up the mock client
    mock_client.collections.get.return_value = mock_collection
    mock_client.collections.exists.return_value = True
    mock_client.is_live.return_value = True

    # Mock the weaviate.connect_to_local function
    with patch('weaviate.connect_to_local', return_value=mock_client) as mock_connect:
        yield mock_client


def test_weaviate_client_initialization(mock_weaviate):
    """Test WeaviateClient initialization and collection setup."""
    client = WeaviateClient()
    assert client.client == mock_weaviate
    mock_weaviate.collections.exists.assert_called()


def test_is_alive(mock_weaviate):
    """Test is_alive method."""
    client = WeaviateClient()
    assert client.is_alive() is True
    mock_weaviate.is_live.assert_called_once()


def test_close(mock_weaviate):
    """Test close method."""
    client = WeaviateClient()
    client.close()
    mock_weaviate.close.assert_called_once()


def test_add_embeddings(mock_weaviate):
    """Test adding embeddings to a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    embeddings = [0.1, 0.2, 0.3]
    properties = {"text": "test text", "name": "test name"}

    uuid = client.add_embeddings(collection_name, embeddings, properties)

    assert uuid == "test-uuid"
    mock_weaviate.collections.get.assert_called_with(collection_name)
    mock_weaviate.collections.get.return_value.data.insert.assert_called_once_with(
        properties=properties, vector=embeddings
    )


def test_get_all_embeddings(mock_weaviate):
    """Test retrieving all embeddings from a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value

    results = client.get_all_embeddings(collection_name)

    assert len(results) == 2
    assert results[0]["id"] == "test-uuid-1"
    assert results[0]["text"] == "test text"
    assert results[0]["vector"] == [0.1, 0.2, 0.3]
    mock_weaviate.collections.get.assert_called_with(collection_name)


def test_get_embeddings_by_property(mock_weaviate):
    """Test retrieving embeddings by property value."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    property_name = "name"
    property_value = "test name"

    results = client.get_embeddings_by_property(
        collection_name, property_name, property_value
    )

    assert len(results) == 1
    assert results[0]["id"] == "test-uuid-1"
    assert results[0]["properties"] == {"text": "test text", "name": "test name"}
    mock_weaviate.collections.get.assert_called_with(collection_name)


def test_search_by_multiple_properties(mock_weaviate):
    """Test searching by multiple property filters."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    property_filters = {
        "category": "math",
        "difficulty": 3,
        "tags": ["algebra", "calculus"],
    }

    results = client.search_by_multiple_properties(collection_name, property_filters)

    assert len(results) == 1
    mock_weaviate.collections.get.assert_called_with(collection_name)


def test_get_weaviate_client_singleton():
    """Test that get_weaviate_client returns a singleton instance."""
    with patch('weaviate.connect_to_local') as mock_connect:
        client1 = get_weaviate_client()
        client2 = get_weaviate_client()
        assert client1 is client2


def test_collection_does_not_exist(mock_weaviate):
    """Test behavior when collection does not exist."""
    mock_weaviate.collections.exists.return_value = False
    client = WeaviateClient()

    # Test that attempting to use a non-existent collection raises ValueError
    with pytest.raises(ValueError, match="Collection 'Competency' does not exist"):
        client.add_embeddings(CollectionNames.COMPETENCY.value, [0.1, 0.2, 0.3])


def test_error_handling(mock_weaviate):
    """Test error handling in various methods."""
    client = WeaviateClient()

    # Test is_alive with connection error
    mock_weaviate.is_live.side_effect = Exception("Connection error")
    assert client.is_alive() is False

    # Test add_embeddings with invalid collection
    mock_weaviate.collections.exists.return_value = False
    with pytest.raises(
        ValueError, match="Collection 'invalid_collection' does not exist"
    ):
        client.add_embeddings("invalid_collection", [0.1, 0.2, 0.3])
