import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock, MagicMock
import numpy as np

# Create mocks before any other imports
mock_weaviate_client = MagicMock()
mock_sentence_transformer = MagicMock()

# Patch the WeaviateClient instance before importing router
with patch('atlasml.clients.weaviate.weaviate_client', mock_weaviate_client):
    from atlasml.routers.competency import router
    from atlasml.ml.VectorEmbeddings import FallbackModel

app = FastAPI()
app.include_router(router)

client = TestClient(app)

# Mock response for embeddings
MOCK_EMBEDDING_VECTOR = np.random.rand(384).tolist()  # Assuming 384-dimensional embeddings

# TODO: FIX THIS TEST
# @pytest.fixture(autouse=True)
# def setup_mocks():
#     with patch('sentence_transformers.SentenceTransformer', autospec=True) as mock_st:
#         mock_st.return_value.encode.return_value = MOCK_EMBEDDING_VECTOR
#         yield

# def test_generate_competency_success():
#     request_data = {
#         "description": "Test input",
#         "id": "550e8400-e29b-41d4-a716-446655440000"
#     }
    
#     response = client.post("/generate-embedings", json=request_data)
    
#     assert response.status_code == 200
#     response_data = response.json()
#     assert "embedings" in response_data
    
#     mock_sentence_transformer.encode.assert_called_once_with(request_data["description"])
#     mock_weaviate_client.add_embeddings.assert_called_once_with(
#         request_data["id"],
#         request_data["description"],
#         MOCK_EMBEDDING_VECTOR
#     )

# def test_generate_competency_batch_success():
#     request_data = {
#         "competencies": [
#             {
#                 "description": "Test input 1",
#                 "id": "550e8400-e29b-41d4-a716-446655440000"
#             },
#             {
#                 "description": "Test input 2",
#                 "id": "550e8400-e29b-41d4-a716-446655440001"
#             }
#         ]
#     }
    
#     response = client.post("/generate-embedings-batch", json=request_data)
    
#     assert response.status_code == 200
#     response_data = response.json()
#     assert "embedings" in response_data
    
#     assert mock_sentence_transformer.encode.call_count == len(request_data["competencies"])
#     assert mock_weaviate_client.add_embeddings.call_count == len(request_data["competencies"])

def test_generate_competency_invalid_request():
    """Test invalid request with missing required field"""
    response = client.post("/generate-embedings", json={})
    
    assert response.status_code == 422
    
    response_data = response.json()
    assert "detail" in response_data
    assert response_data["detail"][0]["loc"] == ["body", "id"]
    assert response_data["detail"][0]["msg"] == "Field required"