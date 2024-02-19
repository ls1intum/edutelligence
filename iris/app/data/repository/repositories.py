import weaviate

from data.repository.repository_schema import init_schema


class Repositories:

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def retrieve(self, question:str):
        pass

    def ingest(self, repositories: dict[str, str]):
        pass

    def search(self, query, k=3, filter=None):
        pass

    def create_tree_structure(self):
        pass
