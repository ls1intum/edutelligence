import pytest
from fastapi.testclient import TestClient
from atlasml.app import app

client = TestClient(app)

def test_authentication_wrong_secret(test_env):
    response = client.post("/api/v1/competency/suggest", json={}, headers={"Authorization": "wrong-secret"})
    assert response.status_code == 403

def test_authentication_no_secret(test_env):
    response = client.post("/api/v1/competency/suggest", json={}, headers={"Authorization": ""})
    assert response.status_code == 401

def test_suggest_competencies(test_env):
    # Test data
    request_data = {
        "id": "test-id-1",
        "description": "Test competency suggestion",
    }
    
    # Make request to suggest endpoint
    response = client.post("/api/v1/competency/suggest", json=request_data, headers={"Authorization": "secret-token"})
    
    # Assert response
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_save_competencies(test_env):
    # Test data
    request_data = {
        "id": "test-id-1",
        "description": "Test competency save request",
        "competencies": [
            {
                "title": "Test Competency 1",
                "description": "Test competency description 1",
                "taxonomy": "R"
            },
            {
                "title": "Test Competency 2",
                "description": "Test competency description 2",
                "taxonomy": "U"
            }
        ],
        "competency_relations": []
    }
    
    # Make request to save endpoint
    response = client.post("/api/v1/competency/save", json=request_data, headers={"Authorization": "secret-token"})
    
    # Assert response
    assert response.status_code == 200
    assert isinstance(response.json(), list)
