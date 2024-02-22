import os
import weaviate
from app.data.repository_schema import init_schema, RepositoryChunk
from langchain.text_splitter import (
    Language,
    RecursiveCharacterTextSplitter,
)
from app.llm.langchain.iris_langchain_embedding_model import IrisLangchainEmbeddingModel
from app.llm import BasicRequestHandler
from data.Ingestion.abstract_ingestion import AbstractIngestion

CHUNKSIZE = 512
OVERLAP = 51


def split_code(code: str, language: Language, chunk_size: int, chunk_overlap: int):
    """
    Split the code into chunks of 1500 characters with an overlap of 100 characters
    """
    python_splitter = RecursiveCharacterTextSplitter.from_language(
        language=language, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return python_splitter.create_documents(code)


def chunk_files(path: str):
    """
    Chunk the code files in the root directory
    """
    files_contents = []
    for directory_path, subdir, files in os.walk(path):
        for filename in files:
            if filename.endswith(".java"):
                file_path = os.path.join(directory_path, filename)
                with open(file_path, "r") as file:
                    code = file.read()
                files_contents.append(
                    {RepositoryChunk.FILEPATH: filename, RepositoryChunk.CONTENT: code}
                )
    for file in files_contents:
        chunks = split_code(
            file[RepositoryChunk.CONTENT], Language.JAVA, CHUNKSIZE, OVERLAP
        )
        for chunk in chunks:
            files_contents.append(
                {
                    RepositoryChunk.CONTENT: chunk.page_content,
                    RepositoryChunk.COURSE_ID: "tbd",
                    RepositoryChunk.EXERCISE_ID: "tbd",
                    RepositoryChunk.REPOSITORY_ID: "tbd",
                    RepositoryChunk.FILEPATH: file[RepositoryChunk.FILEPATH],
                }
            )
    return files_contents


class RepositoryIngestion(AbstractIngestion):
    """
    Ingest the repositories into the weaviate database
    """

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)
        self.request_handler = BasicRequestHandler("gpt35")
        self.iris_embedding_model = IrisLangchainEmbeddingModel(self.request_handler)

    def ingest(self, repo_path) -> bool:
        """
        Ingest the repositories into the weaviate database
        """
        chunks = chunk_files(self, repo_path)
        with self.collection.batch.dynamic() as batch:
            for chunk in enumerate(chunks):
                embed_chunk = self.iris_embedding_model.embed_query(
                    chunk[RepositoryChunk.CONTENT]
                )
                batch.add_object(properties=chunk, vector=embed_chunk)
        return True

    def update(self, repository: dict[str, str]):  # this is most likely not necessary
        """
        Update the repository in the weaviate database
        """
        pass
