import weaviate
import os

from lecture.lectures import Lectures
from repository.repositories import Repositories


class VectorDatabase:
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
        client = weaviate.connect_to_wcs(
            cluster_url=os.getenv(
                "https://try-repository-pipeline-99b1nlo4.weaviate.network"
            ),  # Replace with your WCS URL
            auth_credentials=weaviate.auth.AuthApiKey(
                os.getenv("2IPqwB6mwGMIs92UJ3StB0Wovj0MquBxs9Ql")
            ),  # Replace with your WCS key
        )
        print(client.is_ready())
        self.repositories = Repositories(self.client)
        self.lectures = Lectures(self.client)

    def __del__(self):
        # Close the connection to Weaviate when the object is deleted
        self.client.close()
