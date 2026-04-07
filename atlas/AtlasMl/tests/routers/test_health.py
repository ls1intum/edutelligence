from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlasml.clients.weaviate import CollectionNames
from atlasml.routers.health import router
from tests.conftest import MockWeaviateClient

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_health_endpoint():
    mock_client = MockWeaviateClient()

    with patch("atlasml.routers.health.get_weaviate_client", return_value=mock_client):
        response = client.get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {
            "api": {"status": "ok"},
            "weaviate": {
                "status": "ok",
                "collections": {
                    CollectionNames.EXERCISE.value: {"status": "ok"},
                    CollectionNames.COMPETENCY.value: {"status": "ok"},
                    CollectionNames.SEMANTIC_CLUSTER.value: {"status": "ok"},
                },
            },
        },
    }
    assert response.headers["content-type"] == "application/json"


def test_health_endpoint_returns_503_when_weaviate_is_unreachable():
    mock_client = MockWeaviateClient()
    mock_client.set_alive_status(False)

    with patch("atlasml.routers.health.get_weaviate_client", return_value=mock_client):
        response = client.get("/api/v1/health/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "components": {
            "api": {"status": "ok"},
            "weaviate": {
                "status": "error",
                "message": "Weaviate is unreachable",
            },
        },
    }


def test_health_endpoint_returns_503_when_required_collection_is_missing():
    mock_client = MockWeaviateClient()
    mock_client.collections.delete(CollectionNames.SEMANTIC_CLUSTER.value)

    with patch("atlasml.routers.health.get_weaviate_client", return_value=mock_client):
        response = client.get("/api/v1/health/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "components": {
            "api": {"status": "ok"},
            "weaviate": {
                "status": "error",
                "collections": {
                    CollectionNames.EXERCISE.value: {"status": "ok"},
                    CollectionNames.COMPETENCY.value: {"status": "ok"},
                    CollectionNames.SEMANTIC_CLUSTER.value: {"status": "missing"},
                },
                "message": "Missing required collections: SemanticCluster",
            },
        },
    }
