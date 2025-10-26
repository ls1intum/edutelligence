"""
Tests for video storage service
"""

# pylint: disable=redefined-outer-name,unused-argument

from fastapi.testclient import TestClient

from nebula.video_storage.app import app


def test_app_starts():
    """Test that the app starts correctly"""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Nebula Video Storage Service is running"
    assert "endpoints" in data


def test_health_check():
    """Test the health check endpoint"""
    client = TestClient(app)
    response = client.get("/video-storage/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_test_endpoint():
    """Test the test endpoint"""
    client = TestClient(app)
    response = client.get("/video-storage/test")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Video storage service is up"
    assert data["status"] == "ok"
