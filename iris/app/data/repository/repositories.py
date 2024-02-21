import os
import weaviate
from repository_schema import init_schema, RepositoryChunk
from langchain.text_splitter import (
    Language,
    RecursiveCharacterTextSplitter,
)


class Repositories:

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def split_code(self, code: str, language: Language, chunk_size: int, chunk_overlap: int):
        """
        Split the code into chunks of 1500 characters with an overlap of 100 characters
        """
        python_splitter = RecursiveCharacterTextSplitter.from_language(
            language=language, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return python_splitter.create_documents(code)

    def chunk_files(self, files: [dict[str, str]]):
        """
        Chunk the code files in the root directory
        """
        files_contents = []
        # for directory_path, subdir, files in os.walk(root_directory_path):
        #    for filename in files:
        #        if filename.endswith('.py'):
        #            file_path = os.path.join(directory_path, filename)
        #            with open(file_path, 'r') as file:
        #                code = file.read()
        for file in files:
            chunks = self.split_code(file[RepositoryChunk.CONTENT], Language.JAVA, 1500, 100)
            for chunk in chunks:
                files_contents.append(
                    {
                        RepositoryChunk.CONTENT: chunk,
                        RepositoryChunk.COURSE_ID: file[RepositoryChunk.COURSE_ID],
                        RepositoryChunk.EXERCISE_ID: file[RepositoryChunk.EXERCISE_ID],
                        RepositoryChunk.REPOSITORY_ID: file[RepositoryChunk.REPOSITORY_ID],
                        RepositoryChunk.FILEPATH: file[RepositoryChunk.FILEPATH]
                    }
                )
        return files_contents

    def retrieve(self, query_vector: list[float]):
        """
        Retrieve the top 3 most similar chunks to the query vector
        """
        response = self.collection.query.near_vector(
            near_vector=query_vector,
            limit=3,  # Return the top 3 most similar chunks
            # return_metadata=wvc.query.MetadataQuery()
        )
        return response

    def ingest(self, repositories: [dict[str, str]]):
        chunks = self.chunk_files(self, repositories)
        with self.collection.batch.dynamic() as batch:
            for chunk in enumerate(chunks):
                # embed_chunk = llm.embed(chunk[RepositoryChunk.CONTENT]) # Embed the chunk content
                embed_chunk = [0.0, 0.0, 0.0] # Placeholder for the embedding
                batch.add_object(
                    properties=chunk,
                    vector=embed_chunk
                )
    def update(self, repository: dict[str, str]):# this is most likely not necessary
        pass

    def create_tree_structure(self):
        pass
