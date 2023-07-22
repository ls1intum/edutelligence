import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.cache import cache_store


@pytest.fixture(autouse=True)
def clean_cache_store():
    cache_store.flushdb()
    yield
    cache_store.flushdb()


@pytest.fixture(scope="session")
def test_cache_store():
    return cache_store


@pytest.fixture(scope="session")
def test_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def headers():
    return {"Authorization": "secret"}
