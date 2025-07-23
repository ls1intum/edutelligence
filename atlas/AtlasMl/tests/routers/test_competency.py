import pytest
from fastapi.testclient import TestClient
from atlasml.app import app
from unittest.mock import patch, MagicMock
import numpy as np

client = TestClient(app)

def test_authentication_wrong_secret(test_env):
    response = client.post("/api/v1/competency/suggest", json={}, headers={"Authorization": "wrong-secret"})
    assert response.status_code == 403

def test_authentication_no_secret(test_env):
    response = client.post("/api/v1/competency/suggest", json={}, headers={"Authorization": ""})
    assert response.status_code == 401

def test_suggest_competencies(test_env, mock_generate_embeddings_openai):
    mock_weaviate = MagicMock()
    fake_vector = [0.1, 0.2, 0.3]  # or use list(np.random.rand(1536)) if you want to simulate real size

    # Make sure clusters and competencies both have vectors of the same length
    mock_weaviate.get_all_embeddings.side_effect = [
        [{"id": "cid1", "vector": {"default": fake_vector}, "properties": {"cluster_id": "cid1"}}],  # clusters
        [{"id": "comp1", "properties": {"competency_id": "comp1", "title": "t", "description": "d", "cluster_id": "cid1"}, "vector": {"default": fake_vector}}]  # competencies
    ]
    mock_weaviate.get_embeddings_by_property.return_value = [
        {"properties": {"competency_id": "comp1", "title": "t", "description": "d", "cluster_id": "cid1"}, "vector": {"default": fake_vector}}
    ]
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.get_weaviate_client", return_value=mock_weaviate):
        response = client.post("/api/v1/competency/suggest", json={"description": "Test"}, headers={"Authorization": "secret-token"})
        assert response.status_code == 200

def test_save_competencies(test_env):
    # Test data with proper structure matching SaveCompetencyRequest model
    request_data = {
        "id": "test-id-1",
        "description": "Test competency save request",
        "competencies": [
            {
                "id": "comp-1",  # Required field for Competency model
                "title": "Test Competency 1",
                "description": "Test competency description 1",
                "taxonomy": "R"  # Must be one of: R, U, Y, A, E, C
            },
            {
                "id": "comp-2",  # Required field for Competency model
                "title": "Test Competency 2",
                "description": "Test competency description 2",
                "taxonomy": "U"  # Must be one of: R, U, Y, A, E, C
            }
        ],
        "competency_relations": []  # Empty list of CompetencyRelation objects
    }
    
    # Make request to save endpoint
    response = client.post("/api/v1/competency/save", json=request_data, headers={"Authorization": "secret-token"})
    
    # Assert response
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_save_competencies_with_relations(test_env):
    """Test saving competencies with relations between them."""
    request_data = {
        "id": "test-id-2",
        "description": "Test competency save request with relations",
        "competencies": [
            {
                "id": "comp-3",
                "title": "Parent Competency",
                "description": "A parent competency",
                "taxonomy": "A"
            },
            {
                "id": "comp-4",
                "title": "Child Competency",
                "description": "A child competency",
                "taxonomy": "U"
            }
        ],
        "competency_relations": [
            {
                "tail_competency_id": "comp-4",
                "head_competency_id": "comp-3",
                "relation_type": "SUBSET"
            }
        ]
    }
    
    response = client.post("/api/v1/competency/save", json=request_data, headers={"Authorization": "secret-token"})
    
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_save_competencies_invalid_taxonomy(test_env):
    """Test that invalid taxonomy values are rejected."""
    request_data = {
        "id": "test-id-3",
        "description": "Test with invalid taxonomy",
        "competencies": [
            {
                "id": "comp-5",
                "title": "Invalid Competency",
                "description": "Test competency with invalid taxonomy",
                "taxonomy": "INVALID"  # This should cause a validation error
            }
        ],
        "competency_relations": []
    }
    
    response = client.post("/api/v1/competency/save", json=request_data, headers={"Authorization": "secret-token"})
    
    # Should return 422 Unprocessable Entity for invalid taxonomy
    assert response.status_code == 422

def test_save_competencies_missing_required_fields(test_env):
    """Test that missing required fields are rejected."""
    request_data = {
        "id": "test-id-4",
        "description": "Test with missing fields",
        "competencies": [
            {
                # Missing "id" field - should cause validation error
                "title": "Missing ID Competency",
                "description": "Test competency missing id field",
                "taxonomy": "R"
            }
        ],
        "competency_relations": []
    }
    
    response = client.post("/api/v1/competency/save", json=request_data, headers={"Authorization": "secret-token"})
    
    # Should return 422 Unprocessable Entity for missing required fields
    assert response.status_code == 422
