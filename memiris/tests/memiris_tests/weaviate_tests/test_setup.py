import pytest
from requests import Response, get
from testcontainers.core.waiting_utils import (  # type: ignore[import-untyped]
    wait_container_is_ready,
)
from testcontainers.weaviate import WeaviateContainer  # type: ignore


class WeaviateContainerFixed(WeaviateContainer):
    """
    This class extends the WeaviateContainer from testcontainers to fix
    the _connect method, ensuring it properly checks if the Weaviate service
    is ready by querying the correct endpoint.
    """

    @wait_container_is_ready(ConnectionError)
    def _connect(self) -> None:
        url = (
            f"http://{self.get_http_host()}:{self.get_http_port()}/v1/.well-known/ready"
        )
        try:
            response: Response = get(url, timeout=5)
            if response.status_code != 200:
                raise ConnectionError(
                    f"Weaviate is not ready. Status code: {response.status_code}"
                )
        except Exception as e:
            raise ConnectionError("Failed to connect to Weaviate.") from e


class WeaviateTest:

    @pytest.fixture(scope="session")
    def weaviate_client(self, request):
        weaviate_container = WeaviateContainerFixed(
            image="cr.weaviate.io/semitechnologies/weaviate:1.34.10",
            env_vars={
                "AUTOSCHEMA_ENABLED": "false",
                "DISABLE_TELEMETRY": "true",
            },
        )
        max_retries = 5
        for attempt in range(0, max_retries):
            try:
                weaviate_container.start()
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Failed to start Weaviate container after {max_retries} attempts."
                    ) from e
                print(
                    f"Attempt {attempt + 1}/{max_retries} failed to start Weaviate container: {e}"
                )
                continue

        def remove_container():
            try:
                weaviate_container.stop()
            except Exception as e:
                print(f"Failed to stop Weaviate container: {e}")

        request.addfinalizer(remove_container)

        print("Weaviate container started successfully")

        return weaviate_container.get_client()
