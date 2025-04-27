import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from atlasml.routers.competency import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)
def test_generate_competency_success():
    request_data = {"description": "Test input", "id": "1"}
    
    response = client.post("/generate-embedings", json=request_data)
    
    assert response.status_code == 200
    response_data = response.json()
    
    assert "competencies" in response_data
    assert isinstance(response_data["competencies"], list)
    assert len(response_data["competencies"]) > 0
    
    first_competency = response_data["competencies"][0]
    assert first_competency["title"] == "Competency 1"
    assert first_competency["description"] == "Description 1"
    assert first_competency["taxonomy"] == "R"

def test_generate_competency_invalid_request():
    """Test invalid request with missing required field"""
    response = client.post("/generate-embedings", json={})
    
    # Ensure FastAPI returns a validation error
    assert response.status_code == 422
    
    response_data = response.json()

    assert "detail" in response_data
    assert response_data["detail"][0]["loc"] == ["body", "id"]
    assert response_data["detail"][0]["msg"] == "Field required"