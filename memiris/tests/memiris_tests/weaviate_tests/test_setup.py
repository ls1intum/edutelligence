import pytest
from testcontainers.core.config import testcontainers_config
from testcontainers.weaviate import WeaviateContainer  # type: ignore


class WeaviateTest:

    @pytest.fixture(scope="session", autouse=True)
    def weaviate_container(self, request):
        # Ensure this Weaviate version is the one you intend to use.
        # I've updated it to 1.34.10 based on your earlier statement.
        weaviate_container = WeaviateContainer(
            "cr.weaviate.io/semitechnologies/weaviate:1.34.10",
            environ={
                "DISABLE_TELEMETRY": "true",
            },
        ).with_startup_timeout(120)
        
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
        return weaviate_container
