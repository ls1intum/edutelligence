import pytest
from testcontainers.core.config import testcontainers_config
from testcontainers.weaviate import WeaviateContainer  # type: ignore

# Increase timeout for CI environments where Weaviate may take longer to start
testcontainers_config.timeout = 120


class WeaviateTest:

    @pytest.fixture(scope="session")
    def weaviate_client(self, request):
        weaviate_container = WeaviateContainer(
            image="cr.weaviate.io/semitechnologies/weaviate:1.34.10",
            env_vars={
                "AUTOSCHEMA_ENABLED": "false",
                "DISABLE_TELEMETRY": "true",
            },
        )
        weaviate_container.start()

        def remove_container():
            try:
                weaviate_container.stop()
            except Exception as e:
                print(f"Failed to stop Weaviate container: {e}")

        request.addfinalizer(remove_container)

        print("Weaviate container started successfully")

        return weaviate_container.get_client()
