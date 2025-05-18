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
        weaviate_container.start()

        def remove_container():
            weaviate_container.stop()

        request.addfinalizer(remove_container)

        return weaviate_container.get_client()
