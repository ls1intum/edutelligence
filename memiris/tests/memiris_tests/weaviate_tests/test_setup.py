import pytest
from testcontainers.weaviate import WeaviateContainer  # type: ignore


class WeaviateTest:

    @pytest.fixture(scope="session")
    def weaviate_client(self, request):
        weaviate_container = WeaviateContainer(
            image="cr.weaviate.io/semitechnologies/weaviate:1.30.3",
            env_vars={
                "AUTOSCHEMA_ENABLED": "false",
                "DISABLE_TELEMETRY": "true",
            },
        )
        for _ in range(0, 5):
            try:
                weaviate_container.start()
                break
            except Exception as e:
                print(f"Failed to start Weaviate container: {e}")
                continue

        def remove_container():
            weaviate_container.stop()

        request.addfinalizer(remove_container)

        print("Weaviate container started successfully")

        return weaviate_container.get_client()
