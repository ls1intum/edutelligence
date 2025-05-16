import pytest
from fastapi.testclient import TestClient
from nebula.transcript.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def authorized_headers():
    return {"Authorization": "nebula-secret"}


@pytest.fixture
def invalid_headers():
    return {"Authorization": "invalid-token"}
