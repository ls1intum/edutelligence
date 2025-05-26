import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from atlasml.routers.competency import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)

@pytest.fixture
def mock_weaviate_client():
    mock_client = MagicMock()
    mock_filter = MagicMock()
    
    # Create a mock for the Filter class
    mock_filter.by_property.return_value.equal.return_value = mock_filter
    
    with patch('atlasml.clients.weaviate.get_weaviate_client') as mock_getter, \
         patch('atlasml.clients.weaviate.WeaviateClient') as mock_class, \
         patch('atlasml.clients.weaviate.Filter', return_value=mock_filter):
        mock_getter.return_value = mock_client
        mock_class.return_value = mock_client
        yield mock_client

def test_generate_competency_success(mock_weaviate_client):
    request_data = {"description": "Test input", "id": "550e8400-e29b-41d4-a716-446655440000"}
    
    # Mock the add_embeddings method
    mock_weaviate_client.add_embeddings.return_value = "test-uuid"
    
    response = client.post("/generate-embedings", json=request_data)
    
    assert response.status_code == 200
    response_data = response.json()
    
    assert "embedings" in response_data
    assert isinstance(response_data["embedings"], list)
    
    # Verify the mock was called
    mock_weaviate_client.add_embeddings.assert_called_once()

def test_generate_competency_invalid_request():
    """Test invalid request with missing required field"""
    response = client.post("/generate-embedings", json={})
    
    # Ensure FastAPI returns a validation error
    assert response.status_code == 422
    
    response_data = response.json()

    assert "detail" in response_data
    assert response_data["detail"][0]["loc"] == ["body", "id"]
    assert response_data["detail"][0]["msg"] == "Field required"