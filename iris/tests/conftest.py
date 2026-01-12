import atexit
import os
import time
from pathlib import Path
from unittest.mock import patch

import requests
import weaviate
from testcontainers.core.container import DockerContainer

ROOT = Path(__file__).resolve().parent.parent

# Set config paths before imports trigger Settings loading.
os.environ.setdefault("APPLICATION_YML_PATH", str(ROOT / "application.example.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(ROOT / "llm_config.example.yml"))

TEST_WEAVIATE_HOST = "localhost"
TEST_WEAVIATE_HTTP_PORT = 8001
TEST_WEAVIATE_GRPC_PORT = 50051

_TEST_WEAVIATE_CLIENT = None
_TEST_WEAVIATE_CONTAINER = None
_REAL_CONNECT_TO_LOCAL = weaviate.connect_to_local


def wait_for_weaviate(port, timeout=30):
    url = f"http://{TEST_WEAVIATE_HOST}:{port}/v1/.well-known/ready"
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return True
        except requests.exceptions.RequestException:
            time.sleep(0.5)
    return False


def get_or_start_weaviate_container():
    global _TEST_WEAVIATE_CONTAINER

    if _TEST_WEAVIATE_CONTAINER is None:
        _TEST_WEAVIATE_CONTAINER = (
            DockerContainer("cr.weaviate.io/semitechnologies/weaviate:1.32.2")
            .with_command(
                [
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(TEST_WEAVIATE_HTTP_PORT),
                    "--scheme",
                    "http",
                ]
            )
            .with_exposed_ports(TEST_WEAVIATE_HTTP_PORT, TEST_WEAVIATE_GRPC_PORT)
            .with_env("QUERY_DEFAULTS_LIMIT", "25")
            .with_env("AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED", "true")
            .with_env("DEFAULT_VECTORIZER_MODULE", "none")
            .with_env("ENABLE_MODULES", "")
        )
        _TEST_WEAVIATE_CONTAINER.start()

    return _TEST_WEAVIATE_CONTAINER


def get_or_connect_client():
    global _TEST_WEAVIATE_CLIENT

    if _TEST_WEAVIATE_CLIENT is None:
        container = get_or_start_weaviate_container()
        http_port = int(container.get_exposed_port(TEST_WEAVIATE_HTTP_PORT))
        grpc_port = int(container.get_exposed_port(TEST_WEAVIATE_GRPC_PORT))

        if not wait_for_weaviate(http_port):
            raise RuntimeError("Test Weaviate container did not become ready")

        _TEST_WEAVIATE_CLIENT = _REAL_CONNECT_TO_LOCAL(
            host=TEST_WEAVIATE_HOST,
            port=http_port,
            grpc_port=grpc_port,
        )

    return _TEST_WEAVIATE_CLIENT


def connect_mock(*args, **kwargs):
    return get_or_connect_client()


def cleanup_weaviate():
    if _TEST_WEAVIATE_CLIENT is not None:
        _TEST_WEAVIATE_CLIENT.close()
    if _TEST_WEAVIATE_CONTAINER is not None:
        _TEST_WEAVIATE_CONTAINER.stop()


atexit.register(cleanup_weaviate)

# Patch globally so imports cannot create a real VectorDatabase connection first.
patcher = patch("iris.vector_database.database.weaviate.connect_to_custom", connect_mock)
patcher.start()
