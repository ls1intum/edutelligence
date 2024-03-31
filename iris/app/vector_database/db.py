import weaviate
from weaviate import WeaviateClient

from .lectureschema import init_lecture_schema
from .repository_schema import init_repository_schema


class VectorDatabase:
    """
    Vector Database class
    """

    client: WeaviateClient

    def __init__(self):
        """weaviate_host = os.getenv("WEAVIATE_HOST")
        weaviate_port = os.getenv("WEAVIATE_PORT")
        assert weaviate_host, "WEAVIATE_HOST environment variable must be set"
        assert weaviate_port, "WEAVIATE_PORT environment variable must be set"
        assert (
            weaviate_port.isdigit()
        ), "WEAVIATE_PORT environment variable must be an integer"
        self._client = weaviate.connect_to_local(
            host=weaviate_host, port=int(weaviate_port)
        )"""
        # Connect to the Weaviate Cloud Service until we set up a proper docker for this project
        self.client = weaviate.connect_to_wcs(
            cluster_url="https://pyrisv2-0r7l130v.weaviate.network",
            # Replace with your WCS URL
            auth_credentials=weaviate.auth.AuthApiKey(
                "K33S5szDoHY8R3Xwp26RT4cvdJkpshdYX8Ly"
            ),
        )  # Replace with your WCS key
        print(self.client.is_ready())
        self.repositories = init_repository_schema(self.client)
        self.lectures = init_lecture_schema(self.client)
