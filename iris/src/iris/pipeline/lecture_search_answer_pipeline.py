import json
import re
import time

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
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
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

        pipeline_id = "lecture_search_answer_pipeline"
        hyde_model = resolve_model(pipeline_id, "default", "hyde", local=local)
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)
        logger.info(
            "LectureSearchAnswerPipeline init | local=%s, hyde_model=%s, answer_model=%s",
            local,
            hyde_model,
            answer_model,
        )

        hyde_completion_args = CompletionArguments(temperature=0.7)
        answer_completion_args = CompletionArguments(
            temperature=0.3, response_format="JSON"
        )
        self.hyde_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=hyde_model),
            completion_args=hyde_completion_args,
        )
        self.answer_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=answer_model),
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
        self, query: str, limit: int = 5, **_kwargs
    ) -> LectureSearchAskResponseDTO:
        """
        Answer a student's question using lecture content retrieved via HyDE.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :return: An answer with source references.
        """
        pipeline_start = time.monotonic()
        logger.info(
            "LectureSearchAnswerPipeline started | query=%r, limit=%d",
            query[:100],
            limit,
        )

        # Step 1: Generate a short hypothetical answer to use as the search vector
        t0 = time.monotonic()
        hypothetical_answer = (self.hyde_prompt | self.hyde_pipeline).invoke(
            {"query": query}
        )
        t1 = time.monotonic()
        self._append_tokens(
            self.hyde_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )
        logger.info(
            "Step 1 HyDE LLM done | duration=%.2fs, output_length=%d",
            t1 - t0,
            len(hypothetical_answer),
        )
        logger.debug("HyDE hypothetical answer | output=%r", hypothetical_answer[:200])

        # Step 2: Search using the hypothetical answer embedding (answer-space → answer-space)
        t2 = time.monotonic()
        sources: list[LectureSearchResultDTO] = (
            self.retriever.search_with_vector_override(
                query=query,
                vector_text=hypothetical_answer,
                alpha=0.7,
                limit=limit,
            )
        )
        t3 = time.monotonic()
        logger.info(
            "Step 2 Weaviate search done | duration=%.2fs, results=%d",
            t3 - t2,
            len(sources),
        )

        if not sources:
            logger.info(
                "LectureSearchAnswerPipeline aborted (no sources) | total=%.2fs",
                t3 - pipeline_start,
            )
            return LectureSearchAskResponseDTO(
                answer="No relevant course material was found for this query.",
                sources=[],
            )

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            logger.info(
                "LectureSearchAnswerPipeline aborted (no grounded sources) | total=%.2fs",
                t3 - pipeline_start,
            )
            return LectureSearchAskResponseDTO(
                answer="No relevant course material was found for this query.",
                sources=[],
            )

        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, Slide {s.lecture_unit.page_number}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        t4 = time.monotonic()
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
        )
        t5 = time.monotonic()
        logger.info("Step 3 Answer LLM done | duration=%.2fs", t5 - t4)

        # Parse structured response — strip markdown code fences if present
        try:
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            parsed = json.loads(cleaned)
            answer = parsed.get("answer", raw)
            used_indices = {
                i - 1
                for i in parsed.get("used_sources", [])
                if isinstance(i, int) and i >= 1
            }
            used_sources = [
                s for i, s in enumerate(grounded_sources) if i in used_indices
            ]
        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            logger.warning(
                "Failed to parse structured answer response, returning all sources"
            )
            answer = raw
            used_sources = grounded_sources

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )

        logger.info(
            "LectureSearchAnswerPipeline done | total=%.2fs (hyde=%.2fs, weaviate=%.2fs, answer=%.2fs)",
            time.monotonic() - pipeline_start,
            t1 - t0,
            t3 - t2,
            t5 - t4,
        )

        return LectureSearchAskResponseDTO(answer=answer, sources=used_sources)
