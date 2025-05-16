from fastapi.testclient import TestClient

from nebula.transcript.app import app

client = TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"].lower() == "ok"
