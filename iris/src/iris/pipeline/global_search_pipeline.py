import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.search.lecture_search_dto import (
    GlobalSearchResponseDTO,
    LectureSearchResultDTO,
)
from iris.domain.search.search_intent_dto import SearchIntent
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.global_search_prompts import (
    answer_system_prompt,
    hyde_system_prompt,
)
from iris.pipeline.shared.global_search_intent_classifier import (
    classify as classify_intent,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.tracing import observe

logger = get_logger(__name__)


class GlobalSearchPipeline(SubPipeline):
    """
    Pipeline that answers a student's question by retrieving relevant course content
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
        super().__init__(implementation_id="global_search_pipeline")
        self.tokens = []
        self.retriever = LectureGlobalSearchRetrieval(client)

        pipeline_id = "global_search_pipeline"
        hyde_model = resolve_model(pipeline_id, "default", "hyde", local=local)
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)

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
                ("user", "Course content:\n{context}\n\nQuestion: {query}"),
            ]
        )

    @observe(name="Global Search Pipeline")
    def __call__(
        self, query: str, limit: int = 5, intent: SearchIntent | None = None, **_kwargs
    ) -> GlobalSearchResponseDTO:
        """
        Answer a student's question using course content retrieved via HyDE.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :param intent: Pre-computed intent (SearchIntent). If None,
                       the classifier is called here.
        :return: An answer with source references.
        """
        # Guard: skip the full LLM pipeline for navigation queries
        if intent is None:
            intent = classify_intent(query)
        logger.debug("Intent classification | query=%r intent=%s", query[:80], intent)
        if intent == SearchIntent.SKIP_AI:
            sources = self.retriever.search(query=query, limit=limit)
            return GlobalSearchResponseDTO(answer=None, sources=sources)

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

        if not sources:
            return GlobalSearchResponseDTO(answer=None, sources=[])

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            return GlobalSearchResponseDTO(answer=None, sources=[])

        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, Slide {s.lecture_unit.page_number}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
        )

        # Parse structured response — strip markdown code fences if present
        try:
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            parsed = json.loads(cleaned)
            answer = parsed.get("answer") or None  # treat null and "" as no answer
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

        # Safety net: if the LLM ignored the null instruction and wrote a refusal
        # instead, suppress it so the client never sees a "not covered" message.
        if answer and re.search(
            r"not (covered|mentioned|discussed|found|available|provided|present|included)"
            r"|not (in|part of) the (course|lecture|material|content|slides)"
            r"|no (mention|reference|explanation|definition|description|information)"
            r"|does not (cover|mention|discuss|provide|include|contain|address)"
            r"|cannot (answer|find|provide|address)",
            answer,
            re.IGNORECASE,
        ):
            logger.info(
                "[ask] LLM refusal detected in answer text — suppressing to null"
            )
            answer = None
            used_sources = []

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )

        return GlobalSearchResponseDTO(answer=answer, sources=used_sources)
