from abc import ABC
from typing import List

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from app.domain import IrisMessageRole, PyrisMessage
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.llm import BasicRequestHandler, CompletionArguments
from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.retrieval.abstract_retrieval import AbstractRetrieval
from app.vector_database.lecture_schema import init_lecture_schema, LectureSchema


def merge_retrieved_chunks(
    basic_retrieved_lecture_chunks, hyde_retrieved_lecture_chunks
) -> List[dict]:
    """
    Merge the retrieved chunks from the basic and hyde retrieval methods. This function ensures that for any
    duplicate IDs, the properties from hyde_retrieved_lecture_chunks will overwrite those from basic_retrieved_lecture_chunks.
    """
    merged_chunks = {}
    for chunk in basic_retrieved_lecture_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    for chunk in hyde_retrieved_lecture_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    return [properties for uuid, properties in merged_chunks.items()]


class LectureRetrieval(AbstractRetrieval, ABC):
    """
    Class for retrieving lecture data from the database.
    """

    def __init__(self, client: WeaviateClient):
        self.collection = init_lecture_schema(client)
        self.llm = BasicRequestHandler("azure-gpt-35-turbo")
        self.llm_embedding = BasicRequestHandler("embedding-small")
        self.reranker_pipeline = RerankerPipeline()

    def retrieval_pipeline(
        self,
        student_query: str,
        hybrid_factor: float,
        result_limit: int,
        course_id: int = None,
    ) -> List[dict]:
        # This part is commented until the next ingestion, because there is no course_language field in the data now
        course_language = "English"
        #    self.collection.query.fetch_objects(
        #    limit=1,
        #    return_properties=[LectureSchema.COURSE_LANGUAGE.value]
        # )
        translated_student_query = self.translate(student_query, course_language)
        generated_query = (
            self.rewrite_student_query(
                student_query, course_language, LectureSchema.COURSE_NAME.value
            )
            if student_query
            else None
        )
        response = self.search_in_db(translated_student_query, 0.5, 10, course_id)
        response_hyde = self.search_in_db(generated_query, 0.5, 10, course_id)

        basic_retrieved_lecture_chunks: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response.objects
        ]
        hyde_retrieved_lecture_chunks: list[dict[str, dict]] = [
            {"id": obj.uuid.int, "properties": obj.properties}
            for obj in response_hyde.objects
        ]
        merged_chunks = merge_retrieved_chunks(
            basic_retrieved_lecture_chunks, hyde_retrieved_lecture_chunks
        )

        selected_chunks_index = self.reranker_pipeline(
            paragraphs=merged_chunks, query=student_query
        )
        return [merged_chunks[int(i)] for i in selected_chunks_index]

    def rewrite_student_query(
        self, student_query: str, language: str, course_name: str
    ) -> str:
        """
        Rewrite the student query to generate fitting lecture content and embed it.
        To extract more relevant content from the vector database.
        """
        prompt = (
            f"You are an AI assistant operating on the Artemis Learning Platform at the Technical University of "
            f"Munich. A student has sent a query regarding the lecture {course_name}. The query is: '{student_query}'. "
            f"Please provide a response in {language}. Craft your response to closely reflect the style and content of "
            f"university lecture materials."
        )
        iris_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )
        response = self.llm.chat(
            [iris_message], CompletionArguments(temperature=0.2, max_tokens=1000)
        )
        return response.contents[0].text_content

    def translate(self, student_query: str, course_language: str) -> str:
        """
        Translate the student query to the course language. For better retrieval.
        """
        prompt = (
            f"You are serving as an AI assistant on the Artemis Learning Platform at the Technical University of "
            f"Munich. A student has sent the following message: {student_query}. Please translate this message into "
            f"{course_language}, ensuring that the context and semantic meaning are preserved. If the message is "
            f"already in {course_language}, please correct any language errors to improve its clarity and accuracy."
        )
        iris_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )
        response = self.llm.chat(
            [iris_message], CompletionArguments(temperature=0.2, max_tokens=1000)
        )
        return response.contents[0].text_content

    def search_in_db(
        self, query: str, hybrid_factor: float, result_limit: int, course_id: int = None
    ):
        """
        Search the query in the database and return the results.
        """
        return self.collection.query.hybrid(
            query=query,
            filters=(
                Filter.by_property(LectureSchema.LECTURE_ID.value).equal(course_id)
                if course_id
                else None
            ),
            alpha=hybrid_factor,
            vector=self.llm_embedding.embed(query),
            return_properties=[
                LectureSchema.PAGE_TEXT_CONTENT.value,
                LectureSchema.PAGE_IMAGE_DESCRIPTION.value,
                LectureSchema.COURSE_NAME.value,
                LectureSchema.PAGE_NUMBER.value,
            ],
            limit=result_limit,
        )
