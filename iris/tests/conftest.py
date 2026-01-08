import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import weaviate
from testcontainers.core.container import DockerContainer

ROOT = Path(__file__).resolve().parent.parent

# Set config paths before imports trigger Settings loading.
os.environ.setdefault("APPLICATION_YML_PATH", str(ROOT / "application.example.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(ROOT / "llm_config.example.yml"))

TEST_WEAVIATE_HOST = "localhost"
TEST_WEAVIATE_PORT = 8002
TEST_WEAVIATE_GRPC_PORT = 50052


@pytest.fixture(scope="session")
def weaviate_container():
    container = (
        DockerContainer("cr.weaviate.io/semitechnologies/weaviate:1.32.2")
        .with_exposed_ports(TEST_WEAVIATE_PORT, TEST_WEAVIATE_GRPC_PORT)
        .with_env("QUERY_DEFAULTS_LIMIT", "25")
        .with_env("AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED", "true")
        .with_env("DEFAULT_VECTORIZER_MODULE", "none")
        .with_env("ENABLE_MODULES", "")
    )

    container.start()

    yield container

    container.stop()


def wait_for_weaviate(port, timeout=30):
    url = f"http://localhost:{port}/v1/.well-known/ready"
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url).status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def weaviate_client(weaviate_container):
    http_port = int(weaviate_container.get_exposed_port(TEST_WEAVIATE_PORT))
    grpc_port = int(weaviate_container.get_exposed_port(TEST_WEAVIATE_GRPC_PORT))

    if not wait_for_weaviate(http_port):
        raise RuntimeError("Test Weaviate container did not become ready")

    client = weaviate.connect_to_local(
        host=TEST_WEAVIATE_HOST,
        port=http_port,
        grpc_port=grpc_port,
    )

    yield client

    client.close()


@pytest.fixture(autouse=True)
def patch_vector_db_init(weaviate_client):
    from iris.vector_database.database import VectorDatabase
    from iris.vector_database.faq_schema import init_faq_schema
    from iris.vector_database.lecture_transcription_schema import (
        init_lecture_transcription_schema,
    )
    from iris.vector_database.lecture_unit_page_chunk_schema import (
        init_lecture_unit_page_chunk_schema,
    )
    from iris.vector_database.lecture_unit_schema import init_lecture_unit_schema
    from iris.vector_database.lecture_unit_segment_schema import (
        init_lecture_unit_segment_schema,
    )

    def _mocked_init(self):
        VectorDatabase.static_client_instance = weaviate_client
        VectorDatabase._static_collections = {
            "lectures": init_lecture_unit_page_chunk_schema(weaviate_client),
            "transcriptions": init_lecture_transcription_schema(weaviate_client),
            "lecture_segments": init_lecture_unit_segment_schema(weaviate_client),
            "lecture_units": init_lecture_unit_schema(weaviate_client),
            "faqs": init_faq_schema(weaviate_client),
        }

        self.client = VectorDatabase.static_client_instance
        collections = VectorDatabase._static_collections
        self.lectures = collections["lectures"]
        self.transcriptions = collections["transcriptions"]
        self.lecture_segments = collections["lecture_segments"]
        self.lecture_units = collections["lecture_units"]
        self.faqs = collections["faqs"]

    with patch.object(VectorDatabase, "__init__", _mocked_init):
        yield
