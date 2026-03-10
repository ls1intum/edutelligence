import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.search.lecture_search_dto import (
    LectureSearchAskResponseDTO,
    LectureSearchResultDTO,
)
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.prompts.lecture_search_prompts import (
    answer_system_prompt,
    hyde_system_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.tracing import observe

logger = get_logger(__name__)


class LectureSearchAnswerPipeline(SubPipeline):
    """
    Pipeline that answers a student's question by retrieving relevant lecture content
    using HyDE (Hypothetical Document Embedding) and then generating a concise answer.

    HyDE improves retrieval precision for Q&A: instead of embedding the question directly,
    it generates a short hypothetical answer first and embeds that. This works because
    answers live closer to answers in the vector space than questions do.
    """

    hyde_llm: IrisLangchainChatModel
    answer_llm: IrisLangchainChatModel
    hyde_pipeline: Runnable
    answer_pipeline: Runnable

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="lecture_search_answer_pipeline")
        self.tokens = []
        self.retriever = LectureGlobalSearchRetrieval(client)

        hyde_model = "gpt-oss:120b" if local else "gpt-4.1-nano"
        answer_model = "gpt-oss:120b" if local else "gpt-4.1-mini"

        hyde_completion_args = CompletionArguments(temperature=0.7)
        answer_completion_args = CompletionArguments(temperature=0.3)
        self.hyde_llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=hyde_model),
            completion_args=hyde_completion_args,
        )
        self.answer_llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=answer_model),
            completion_args=answer_completion_args,
        )
        self.hyde_pipeline = self.hyde_llm | StrOutputParser()
        self.answer_pipeline = self.answer_llm | StrOutputParser()

        self.hyde_prompt = ChatPromptTemplate.from_messages(
            [("system", hyde_system_prompt), ("user", "{query}")]
        )
        self.answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", answer_system_prompt),
                ("user", "Lecture content:\n{context}\n\nQuestion: {query}"),
            ]
        )

    @observe(name="Lecture Search Answer Pipeline")
    def __call__(
        self, query: str, limit: int = 5, **kwargs
    ) -> LectureSearchAskResponseDTO:
        """
        Answer a student's question using lecture content retrieved via HyDE.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :return: An answer with source references.
        """
        # Step 1: Generate a short hypothetical answer to use as the search vector
        hypothetical_answer = (self.hyde_prompt | self.hyde_pipeline).invoke(
            {"query": query}
        )
        self._append_tokens(
            self.hyde_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )
        logger.debug("HyDE hypothetical answer | output=%r", hypothetical_answer[:200])

        # Step 2: Search using the hypothetical answer embedding (answer-space → answer-space)
        sources: list[LectureSearchResultDTO] = (
            self.retriever.search_with_vector_override(
                query=query,
                vector_text=hypothetical_answer,
                alpha=0.7,
                limit=limit,
            )
        )

        # Step 3: Generate the real answer using numbered context
        context = "\n\n".join(
            f"[{i + 1}] {s.snippet}" for i, s in enumerate(sources) if s.snippet
        )
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
        )

        # Parse structured response — strip markdown code fences if present
        try:
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            parsed = json.loads(cleaned)
            answer = parsed.get("answer", raw)
            used_indices = {
                i - 1 for i in parsed.get("used_sources", []) if isinstance(i, int)
            }
            used_sources = [s for i, s in enumerate(sources) if i in used_indices]
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Failed to parse structured answer response, returning all sources"
            )
            answer = raw
            used_sources = sources

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )

        return LectureSearchAskResponseDTO(answer=answer, sources=used_sources)
