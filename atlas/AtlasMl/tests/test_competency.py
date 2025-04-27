import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import numpy as np

from atlasml.routers.competency import router
from atlasml.ml.VectorEmbeddings import FallbackModel

app = FastAPI()
app.include_router(router)

client = TestClient(app)

# Mock response for generate_embeddings
MOCK_EMBEDDING_VECTOR = np.random.rand(384).tolist()  # Assuming 384-dimensional embeddings

@pytest.fixture
def mock_generate_embeddings():
    with patch.object(FallbackModel, 'generate_embeddings', autospec=True) as mock:
        mock.return_value = ("test-uuid", MOCK_EMBEDDING_VECTOR)
        yield mock

def test_generate_competency_success(mock_generate_embeddings):
    request_data = {
        "description": "Test input",
        "id": "550e8400-e29b-41d4-a716-446655440000"
    }
    
    response = client.post("/generate-embedings", json=request_data)
    
    # Assert response
    assert response.status_code == 200
    response_data = response.json()
    assert "embedings" in response_data
    
    # Verify mock was called correctly
    mock_generate_embeddings.assert_called_once_with(
        request_data["id"],
        request_data["description"]
    )

def test_generate_competency_batch_success(mock_generate_embeddings):
    request_data = {
        "competencies": [
            {
                "description": "Test input 1",
                "id": "550e8400-e29b-41d4-a716-446655440000"
            },
            {
                "description": "Test input 2",
                "id": "550e8400-e29b-41d4-a716-446655440001"
            }
        ]
    }
    
    response = client.post("/generate-embedings-batch", json=request_data)
    
    # Assert response
    assert response.status_code == 200
    response_data = response.json()
    assert "embedings" in response_data
    
    # Verify mock was called for each competency
    assert mock_generate_embeddings.call_count == len(request_data["competencies"])

def test_generate_competency_invalid_request():
    """Test invalid request with missing required field"""
    response = client.post("/generate-embedings", json={})
    
    # Ensure FastAPI returns a validation error
    assert response.status_code == 422
    
    response_data = response.json()
    assert "detail" in response_data
    assert response_data["detail"][0]["loc"] == ["body", "id"]
    assert response_data["detail"][0]["msg"] == "Field required"