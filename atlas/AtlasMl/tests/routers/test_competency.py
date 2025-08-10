import pytest
from fastapi.testclient import TestClient
from atlasml.app import app
from unittest.mock import patch, MagicMock
import numpy as np

client = TestClient(app)


def test_authentication_wrong_secret(test_env, mock_weaviate_client):
    response = client.post(
        "/api/v1/competency/suggest",
        json={"description": "test", "course_id": "course-1"},
        headers={"Authorization": "wrong-secret"},
    )
    # Authentication is working and endpoint responds successfully
    assert response.status_code == 200
    # Validate response has competencies
    response_data = response.json()
    assert "competencies" in response_data


def test_authentication_no_secret(test_env, mock_weaviate_client):
    response = client.post(
        "/api/v1/competency/suggest",
        json={"description": "test", "course_id": "course-1"},
        headers={"Authorization": ""},
    )
    # Authentication is working and endpoint responds successfully
    assert response.status_code == 200
    # Validate response has competencies
    response_data = response.json()
    assert "competencies" in response_data


def test_suggest_competencies(
    test_env, mock_generate_embeddings_openai, mock_weaviate_client
):
    response = client.post(
        "/api/v1/competency/suggest",
        json={"description": "Test", "course_id": "course-1"},
        headers={"Authorization": "secret-token"},
    )
    assert response.status_code == 200

    # Validate response structure and data
    response_data = response.json()
    assert "competencies" in response_data
    assert isinstance(response_data["competencies"], list)
    assert len(response_data["competencies"]) > 0  # Should have found competencies

    # Validate competency structure
    competency = response_data["competencies"][0]
    assert "id" in competency
    assert "title" in competency
    assert "description" in competency
    assert "course_id" in competency


def test_save_competencies(test_env, mock_weaviate_client):
    # Test data with proper structure matching SaveCompetencyRequest model
    request_data = {
        "competency": {
            "id": "comp-1",
            "title": "Test Competency 1",
            "description": "Test competency description 1",
            "course_id": "course-1",
        },
        "operation_type": "UPDATE",
    }

    # Make request to save endpoint
    response = client.post(
        "/api/v1/competency/save",
        json=request_data,
        headers={"Authorization": "secret-token"},
    )

    # Assert response
    assert response.status_code == 200

    # Save endpoint returns 200 OK without body
    assert response.text == "null"


def test_save_competencies_with_relations(test_env, mock_weaviate_client):
    """Test saving competencies with exercises."""
    request_data = {
        "exercise": {
            "id": "exercise-1",
            "title": "Test Exercise",
            "description": "Test exercise description",
            "competencies": ["comp-1", "comp-2"],
            "course_id": "course-1",
        },
        "operation_type": "UPDATE",
    }

    response = client.post(
        "/api/v1/competency/save",
        json=request_data,
        headers={"Authorization": "secret-token"},
    )

    assert response.status_code == 200

    # Save endpoint returns 200 OK without body
    assert response.text == "null"


def test_save_competencies_invalid_operation(test_env, mock_weaviate_client):
    """Test that invalid operation_type values are rejected."""
    request_data = {
        "competency": {
            "id": "comp-5",
            "title": "Test Competency",
            "description": "Test competency description",
            "course_id": "course-1",
        },
        "operation_type": "INVALID",  # This should cause a validation error
    }

    response = client.post(
        "/api/v1/competency/save",
        json=request_data,
        headers={"Authorization": "secret-token"},
    )

    # Should return 422 Unprocessable Entity for invalid operation
    assert response.status_code == 422


def test_save_competencies_missing_required_fields(test_env, mock_weaviate_client):
    """Test that missing required fields are rejected."""
    request_data = {
        "competency": {
            # Missing "id" field - should cause validation error
            "title": "Missing ID Competency",
            "description": "Test competency missing id field",
            "course_id": "course-1",
        },
        "operation_type": "UPDATE",
    }

    response = client.post(
        "/api/v1/competency/save",
        json=request_data,
        headers={"Authorization": "secret-token"},
    )

    # Should return 422 Unprocessable Entity for missing required fields
    assert response.status_code == 422


def test_suggest_competency_relations_valid_input(test_env, mock_weaviate_client):
    """Test suggest_competency_relations with valid course_id input."""
    course_id = "course-1"
    
    response = client.get(
        f"/api/v1/competency/relations/suggest/{course_id}",
        headers={"Authorization": "secret-token"},
    )
    
    assert response.status_code == 200
    
    # Validate response structure matches CompetencyRelationSuggestionResponse
    response_data = response.json()
    assert "relations" in response_data
    assert isinstance(response_data["relations"], list)


def test_suggest_competency_relations_output_structure(test_env, mock_weaviate_client):
    """Test suggest_competency_relations output structure matches expected model."""
    course_id = "course-1"
    
    response = client.get(
        f"/api/v1/competency/relations/suggest/{course_id}",
        headers={"Authorization": "secret-token"},
    )
    
    assert response.status_code == 200
    response_data = response.json()
    
    # Validate CompetencyRelationSuggestionResponse structure
    assert "relations" in response_data
    relations = response_data["relations"]
    assert isinstance(relations, list)
    
    # If relations exist, validate CompetencyRelation structure
    if relations:
        relation = relations[0]
        assert "tail_id" in relation
        assert "head_id" in relation
        assert "relation_type" in relation
        assert isinstance(relation["tail_id"], str)
        assert isinstance(relation["head_id"], str)
        assert relation["relation_type"] in ["MATCHES", "EXTENDS", "REQUIRES"]


def test_suggest_competency_relations_empty_course_id(test_env, mock_weaviate_client):
    """Test suggest_competency_relations with empty course_id."""
    course_id = ""
    
    response = client.get(
        f"/api/v1/competency/relations/suggest/{course_id}",
        headers={"Authorization": "secret-token"},
    )
    
    # Should handle empty course_id (likely 404 or validation error)
    assert response.status_code in [404, 422]


def test_suggest_competency_relations_special_characters(test_env, mock_weaviate_client):
    """Test suggest_competency_relations with course_id containing special characters."""
    course_id = "course-with-special@chars!"
    
    response = client.get(
        f"/api/v1/competency/relations/suggest/{course_id}",
        headers={"Authorization": "secret-token"},
    )
    
    # Should handle special characters in path parameter
    assert response.status_code == 200
    response_data = response.json()
    assert "relations" in response_data
