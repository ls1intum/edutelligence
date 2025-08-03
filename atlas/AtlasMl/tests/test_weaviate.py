import pytest

from atlasml.clients.weaviate import (
    CollectionNames,
    WeaviateClient,
    get_weaviate_client,
)


def test_weaviate_client_initialization(mock_weaviate_client):
    """Test WeaviateClient initialization and collection setup."""
    client = WeaviateClient()
    assert client.client == mock_weaviate_client


def test_is_alive(mock_weaviate_client):
    """Test is_alive method."""
    client = WeaviateClient()
    assert client.is_alive() is True


def test_close(mock_weaviate_client):
    """Test close method."""
    client = WeaviateClient()
    client.close()
    assert not client.is_alive()


def test_add_embeddings(mock_weaviate_client):
    """Test adding embeddings to a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    embeddings = [0.1, 0.2, 0.3]
    properties = {"competency_id": "comp-1", "title": "Test Competency"}

    uuid = client.add_embeddings(collection_name, embeddings, properties)

    assert uuid == "test-uuid"


def test_get_all_embeddings(mock_weaviate_client):
    """Test retrieving all embeddings from a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value

    results = client.get_all_embeddings(collection_name)

    assert len(results) == 2
    assert results[0]["id"] == "competency-uuid-1"
    assert results[0]["properties"]["competency_id"] == "comp-1"
    assert results[0]["properties"]["title"] == "Algebra"
    assert results[0]["vector"] == [0.1, 0.2, 0.3]


def test_get_embeddings_by_property(mock_weaviate_client):
    """Test retrieving embeddings by property value."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    property_name = "competency_id"
    property_value = "comp-1"

    results = client.get_embeddings_by_property(
        collection_name, property_name, property_value
    )

    assert len(results) == 1
    assert results[0]["id"] == "competency-uuid-1"
    assert results[0]["properties"]["competency_id"] == "comp-1"
    assert results[0]["properties"]["title"] == "Algebra"


def test_search_by_multiple_properties(mock_weaviate_client):
    """Test searching by multiple property filters."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    property_filters = {
        "competency_id": "comp-1",
        "cluster_similarity_score": 0.85,
    }

    results = client.search_by_multiple_properties(collection_name, property_filters)

    assert len(results) == 1
    assert results[0]["id"] == "competency-uuid-1"


def test_get_weaviate_client_singleton(mock_weaviate_client):
    """Test that get_weaviate_client returns a singleton instance."""
    client1 = get_weaviate_client()
    client2 = get_weaviate_client()
    assert client1 is client2


def test_collection_does_not_exist(mock_weaviate_client):
    """Test behavior when collection does not exist."""
    client = WeaviateClient()
    
    # Test the internal check method directly with a non-existent collection
    with pytest.raises(ValueError, match="Collection 'NonExistentCollection' does not exist"):
        client._check_if_collection_exists("NonExistentCollection")


def test_error_handling(mock_weaviate_client):
    """Test error handling in various methods."""
    client = WeaviateClient()

    # Test add_embeddings with invalid collection
    with pytest.raises(
        ValueError, match="Collection 'invalid_collection' does not exist"
    ):
        client.add_embeddings("invalid_collection", [0.1, 0.2, 0.3])


def test_recreate_collection_success(mock_weaviate_client):
    """Test successful recreation of a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    
    # Should not raise any errors
    client.recreate_collection(collection_name)
    
    # Verify collection still exists after recreation
    assert mock_weaviate_client.collections.exists(collection_name)


def test_recreate_collection_invalid_schema(mock_weaviate_client):
    """Test recreation of collection with invalid schema."""
    client = WeaviateClient()
    invalid_collection_name = "InvalidCollection"
    
    # Test that attempting to recreate a collection without a defined schema raises ValueError
    with pytest.raises(ValueError, match=f"No schema defined for collection '{invalid_collection_name}'"):
        client.recreate_collection(invalid_collection_name)


def test_delete_all_data_from_collection_success(mock_weaviate_client):
    """Test successful deletion of all data from a collection."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    
    # Should not raise any errors
    client.delete_all_data_from_collection(collection_name)
    
    # Verify collection still exists after recreation
    assert mock_weaviate_client.collections.exists(collection_name)


def test_delete_all_data_from_collection_nonexistent(mock_weaviate_client):
    """Test deletion of all data from a non-existent collection."""
    client = WeaviateClient()
    collection_name = "NonExistentCollection"
    
    # Test that attempting to delete from a non-existent collection raises ValueError
    with pytest.raises(ValueError, match=f"Collection '{collection_name}' does not exist"):
        client.delete_all_data_from_collection(collection_name)


def test_recreate_collection_with_different_schemas(mock_weaviate_client):
    """Test recreation of different collection types with their respective schemas."""
    client = WeaviateClient()
    
    # Test recreation of different collection types
    test_collections = [
        CollectionNames.COMPETENCY.value,
        CollectionNames.CLUSTERCENTER.value,
        CollectionNames.EXERCISE.value
    ]
    
    for collection_name in test_collections:
        client.recreate_collection(collection_name)
        # Verify collection exists after recreation
        assert mock_weaviate_client.collections.exists(collection_name)


def test_exercise_collection_data(mock_weaviate_client):
    """Test that Exercise collection returns appropriate schema data."""
    client = WeaviateClient()
    collection_name = CollectionNames.EXERCISE.value
    
    results = client.get_all_embeddings(collection_name)
    
    assert len(results) == 2
    assert results[0]["id"] == "exercise-uuid-1"
    assert results[0]["properties"]["exercise_id"] == "ex-1"
    assert results[0]["properties"]["description"] == "Solve linear equations"
    assert results[0]["properties"]["competency_ids"] == ["comp-1", "comp-2"]


def test_cluster_center_collection_data(mock_weaviate_client):
    """Test that ClusterCenter collection returns appropriate schema data."""
    client = WeaviateClient()
    collection_name = CollectionNames.CLUSTERCENTER.value
    
    results = client.get_all_embeddings(collection_name)
    
    assert len(results) == 1
    assert results[0]["id"] == "cluster-uuid-1"
    assert results[0]["properties"]["cluster_id"] == "cluster-1"
    assert results[0]["properties"]["label_id"] == "algebra-basics"


# Error handling tests
def test_add_embeddings_with_invalid_embeddings(mock_weaviate_client):
    """Test add_embeddings with invalid embeddings parameter."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    
    # Test with None embeddings
    with pytest.raises(ValueError, match="Embeddings must be a non-empty list of floats"):
        client.add_embeddings(collection_name, None)
    
    # Test with empty list
    with pytest.raises(ValueError, match="Embeddings must be a non-empty list of floats"):
        client.add_embeddings(collection_name, [])
    
    # Test with non-list embeddings
    with pytest.raises(ValueError, match="Embeddings must be a non-empty list of floats"):
        client.add_embeddings(collection_name, "not a list")


def test_add_embeddings_query_error():
    """Test add_embeddings with Weaviate query error."""
    from unittest.mock import patch
    from atlasml.clients.weaviate import WeaviateOperationError
    from tests.conftest import MockWeaviateClient
    
    # Create a mock client and configure to fail
    mock_client = MockWeaviateClient()
    collection = mock_client.collections.get(CollectionNames.COMPETENCY.value)
    collection.data.set_fail_insert(True)
    
    with patch('weaviate.connect_to_local', return_value=mock_client):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            client = WeaviateClient()
            
            with pytest.raises(WeaviateOperationError, match="Unexpected error adding embedding"):
                client.add_embeddings(CollectionNames.COMPETENCY.value, [0.1, 0.2, 0.3])


def test_get_embeddings_by_property_with_invalid_params(mock_weaviate_client):
    """Test get_embeddings_by_property with invalid parameters."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    
    # Test with empty property name
    with pytest.raises(ValueError, match="Property name and value must be provided"):
        client.get_embeddings_by_property(collection_name, "", "value")
    
    # Test with empty property value
    with pytest.raises(ValueError, match="Property name and value must be provided"):
        client.get_embeddings_by_property(collection_name, "property", "")


def test_get_embeddings_by_property_query_error():
    """Test get_embeddings_by_property with Weaviate query error."""
    from unittest.mock import patch
    from atlasml.clients.weaviate import WeaviateOperationError
    from tests.conftest import MockWeaviateClient
    
    # Create a mock client and configure to fail
    mock_client = MockWeaviateClient()
    collection = mock_client.collections.get(CollectionNames.COMPETENCY.value)
    collection.query.set_fail_fetch(True)
    
    with patch('weaviate.connect_to_local', return_value=mock_client):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            client = WeaviateClient()
            
            with pytest.raises(WeaviateOperationError, match="Unexpected error getting embeddings by property"):
                client.get_embeddings_by_property(CollectionNames.COMPETENCY.value, "competency_id", "comp-1")


def test_get_all_embeddings_query_error():
    """Test get_all_embeddings with Weaviate query error."""
    from atlasml.clients.weaviate import WeaviateOperationError
    from unittest.mock import patch
    from tests.conftest import MockWeaviateClient
    
    # Create a mock client and configure to fail
    mock_client = MockWeaviateClient()
    collection = mock_client.collections.get(CollectionNames.COMPETENCY.value)
    
    with patch('weaviate.connect_to_local', return_value=mock_client):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            client = WeaviateClient()
            
            # Mock the iterator to raise an exception
            with patch.object(collection, 'iterator', side_effect=Exception("Mock iterator error")):
                with pytest.raises(WeaviateOperationError, match="Unexpected error getting embeddings"):
                    client.get_all_embeddings(CollectionNames.COMPETENCY.value)


def test_update_property_by_id_with_invalid_params(mock_weaviate_client):
    """Test update_property_by_id with invalid parameters."""
    client = WeaviateClient()
    collection_name = CollectionNames.COMPETENCY.value
    
    # Test with empty ID
    with pytest.raises(ValueError, match="ID and properties must be provided"):
        client.update_property_by_id(collection_name, "", {"title": "Updated"})
    
    # Test with empty properties
    with pytest.raises(ValueError, match="ID and properties must be provided"):
        client.update_property_by_id(collection_name, "test-id", {})


def test_update_property_by_id_query_error():
    """Test update_property_by_id with Weaviate query error."""
    from unittest.mock import patch
    from atlasml.clients.weaviate import WeaviateOperationError
    from tests.conftest import MockWeaviateClient
    
    # Create a mock client and configure to fail
    mock_client = MockWeaviateClient()
    collection = mock_client.collections.get(CollectionNames.COMPETENCY.value)
    collection.data.set_fail_update(True)
    
    with patch('weaviate.connect_to_local', return_value=mock_client):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            client = WeaviateClient()
            
            with pytest.raises(WeaviateOperationError, match="Unexpected error updating property"):
                client.update_property_by_id(CollectionNames.COMPETENCY.value, "test-id", {"title": "Updated"})


def test_is_alive_connection_error(mock_weaviate_client):
    """Test is_alive method when connection fails."""
    client = WeaviateClient()
    
    # Configure mock to fail
    mock_weaviate_client.set_fail_is_live(True)
    
    # Should return False instead of raising exception
    assert client.is_alive() is False


def test_weaviate_connection_error():
    """Test WeaviateClient initialization with connection error."""
    from unittest.mock import patch
    from atlasml.clients.weaviate import WeaviateConnectionError
    
    # Mock weaviate.connect_to_local to raise an exception
    with patch('weaviate.connect_to_local', side_effect=Exception("Connection failed")):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            with pytest.raises(WeaviateConnectionError, match="Unexpected connection error"):
                WeaviateClient()


def test_collection_initialization_error():
    """Test WeaviateClient initialization with collection setup error."""
    from unittest.mock import patch, MagicMock
    from atlasml.clients.weaviate import WeaviateOperationError
    from tests.conftest import MockWeaviateClient
    
    # Create a mock client that will fail during collection setup
    mock_client = MockWeaviateClient()
    mock_client.collections.exists = MagicMock(side_effect=Exception("Collection check failed"))
    
    with patch('weaviate.connect_to_local', return_value=mock_client):
        with patch('atlasml.clients.weaviate.WeaviateClientSingleton._instance', None):
            with pytest.raises(WeaviateOperationError, match="Failed to initialize collections"):
                WeaviateClient()
