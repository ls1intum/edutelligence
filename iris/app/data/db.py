import weaviate
import os

from data.lecture.lectures import Lectures
from data.repository.repositories import Repositories


class VectorDatabase:
    def __init__(self):
        weaviate_host = os.getenv("WEAVIATE_HOST")
        weaviate_port = os.getenv("WEAVIATE_PORT")
        assert weaviate_host, "WEAVIATE_HOST environment variable must be set"
        assert weaviate_port, "WEAVIATE_PORT environment variable must be set"
        assert (
            weaviate_port.isdigit()
        ), "WEAVIATE_PORT environment variable must be an integer"
        self._client = weaviate.connect_to_local(
            host=weaviate_host, port=int(weaviate_port)
        )
        self.repositories = Repositories(self._client)
        self.lectures = Lectures(self._client)

    def __del__(self):
        # Close the connection to Weaviate when the object is deleted
        self._client.close()
