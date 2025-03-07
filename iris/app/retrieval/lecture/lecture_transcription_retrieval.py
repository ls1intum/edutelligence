from typing import List

from langchain_core.output_parsers import StrOutputParser

from app.common.pyris_message import PyrisMessage
from app.domain.retrieval.lecture.lecture_retrieval_dto import LectureUnitRetrievalDTO
from app.llm import (
    CapabilityRequestHandler,
    RequirementList,
    CompletionArguments,
    BasicRequestHandler,
)
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from weaviate import WeaviateClient

from app.pipeline.shared.reranker_pipeline import RerankerPipeline
from app.vector_database.lecture_transcription_schema import (
    init_lecture_transcription_schema,
)


class LectureTranscriptionRetrieval(Pipeline):
    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_transcriptions_retrieval_pipeline")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.25,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = BasicRequestHandler("embedding-small")
        self.pipeline = self.llm | StrOutputParser()
        self.collection = init_lecture_transcription_schema(client)
        self.reranker_pipeline = RerankerPipeline()
        self.tokens = []

    def __call__(
        self,
        rewritten_query: str,
        hypothetical_answer: str,
        lecture_unit_dto: LectureUnitRetrievalDTO,
    ):
        print("LectureTranscriptionRetrieval is running")
        return self

    # 1. Anfrage mit Queries an Weaviate
    # 2. Merge results in eine Liste
    # 3. Reranken
    # 4. DTOs zurückgeben
