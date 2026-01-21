import pytest
from testcontainers.weaviate import WeaviateContainer  # type: ignore


class WeaviateTest:

    @pytest.fixture(scope="session")
    def weaviate_client(self, request):
        weaviate_container = WeaviateContainer(
            image="cr.weaviate.io/semitechnologies/weaviate:1.34.10",
            env_vars={
                "AUTOSCHEMA_ENABLED": "false",
                "DISABLE_TELEMETRY": "true",

                "ENABLE_MODULES": "",
                "DEFAULT_VECTORIZER_MODULE": "none",
                "CLUSTER_HOSTNAME": "node1",
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
