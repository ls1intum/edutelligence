from fastapi.testclient import TestClient
from atlasml.routers.health import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health/")

    # Test status code
    assert response.status_code == 200

    # Test content
    assert response.content == b"[]"

    # Test media type
    assert response.headers["content-type"] == "application/json"
