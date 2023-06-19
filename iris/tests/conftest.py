import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="session")
def test_client():
    with TestClient(app) as c:
        yield c
