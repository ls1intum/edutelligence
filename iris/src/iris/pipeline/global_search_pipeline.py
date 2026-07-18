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
        self.retriever = LectureGlobalSearchRetrieval(client, local=local)

        pipeline_id = "global_search_pipeline"
        hyde_model = resolve_model(pipeline_id, "default", "hyde", local=local)
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=local
        )
        logger.info(
            "Global search pipeline | mode=%s hyde_llm=%s answer_llm=%s embedding=%s",
            "local" if local else "cloud",
            hyde_model,
            answer_model,
            embedding_model,
        )

        hyde_completion_args = CompletionArguments(max_tokens=150)
        answer_completion_args = CompletionArguments(
            response_format="JSON", max_tokens=600
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
        t_hyde = time.perf_counter()
        hypothetical_answer = (self.hyde_prompt | self.hyde_pipeline).invoke(
            {"query": query}
        )
        self._append_tokens(
            self.hyde_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )
        logger.info(
            "[global-search] hyde_ms=%.0f hyde_output=%r",
            (time.perf_counter() - t_hyde) * 1000,
            hypothetical_answer[:300],
        )

        # Step 2: Search using the hypothetical answer embedding (answer-space → answer-space)
        t_retrieval = time.perf_counter()
        sources: list[LectureSearchResultDTO] = (
            self.retriever.search_with_vector_override(
                query=query,
                vector_text=hypothetical_answer,
                alpha=0.5,
                limit=limit,
            )
        )

        # Fallback: if HyDE vector produced no hits (e.g. ambiguous query where HyDE
        # generated off-topic content), retry with the raw query embedding.
        if not sources:
            logger.info(
                "HyDE retrieval returned 0 sources — retrying with keyword-heavy search"
            )
            sources = self.retriever.search_with_vector_override(
                query=query,
                vector_text=query,
                alpha=0.1,
                limit=limit,
            )
        logger.info(
            "[global-search] retrieval_ms=%.0f sources=%d",
            (time.perf_counter() - t_retrieval) * 1000,
            len(sources),
        )

        if not sources:
            logger.info("[global-search] outcome=no_sources query=%r", query[:120])
            return GlobalSearchResponseDTO(answer=None, sources=[])

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            logger.info(
                "[global-search] outcome=no_grounded_sources sources=%d query=%r",
                len(sources),
                query[:120],
            )
            return GlobalSearchResponseDTO(answer=None, sources=[])

        def _location_label(s: LectureSearchResultDTO) -> str:
            page = s.lecture_unit.page_number
            if page == -1:
                meta = s.lecture_unit.display_meta or "video"
                return f"Video @ {meta}"
            return f"Slide {page}"

        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, {_location_label(s)}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        t_answer = time.perf_counter()
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
        )
        # raw_len=0 + output_tokens>0 is the fingerprint of a reasoning model
        # exhausting max_tokens on reasoning and returning an empty message
        # (finish_reason=length) — the call returns WITHOUT an exception.
        answer_usage = self.answer_llm.tokens
        logger.info(
            "[global-search] answer_llm_ms=%.0f raw_len=%d input_tokens=%s "
            "output_tokens=%s",
            (time.perf_counter() - t_answer) * 1000,
            len(raw),
            getattr(answer_usage, "num_input_tokens", None),
            getattr(answer_usage, "num_output_tokens", None),
        )

        # Parse structured response — strip markdown code fences if present
        try:
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                # LaTeX backslashes (e.g. \alpha, \sum) are invalid JSON escape
                # sequences. Escape any backslash not already part of a recognised
                # JSON escape before retrying.
                fixed = re.sub(r'\\(?!["\\/])', r"\\\\", cleaned)
                parsed = json.loads(fixed)
            answer = parsed.get("answer") or None  # treat null and "" as no answer
            if answer is None:
                logger.info("[global-search] outcome=llm_null_json raw=%r", raw[:300])
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
                "[global-search] outcome=parse_failed raw_len=%d raw=%r — "
                "returning raw text as answer with all sources",
                len(raw),
                raw[:300],
            )
            answer = raw
            used_sources = grounded_sources

        # Safety net: if the LLM ignored the null instruction and wrote a short refusal
        # instead of a grounded answer, suppress it so the client never sees a
        # "not covered" message. Only fires on short answers (< 120 chars) to avoid
        # suppressing legitimate answers that mention what the course does not cover.
        if (
            answer
            and len(answer) < 120
            and re.search(
                r"not (covered|mentioned|discussed|found|available|provided|present|included)"
                r"|not (in|part of) the (course|lecture|material|content|slides)"
                r"|no (mention|reference|explanation|definition|description|information)"
                r"|does not (cover|mention|discuss|provide|include|contain|address)"
                r"|cannot (answer|find|provide|address)",
                answer,
                re.IGNORECASE,
            )
        ):
            logger.info(
                "[global-search] outcome=refusal_suppressed suppressed_answer=%r",
                answer,
            )
            answer = None

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )

        if answer:
            logger.info(
                "[global-search] outcome=answered answer_len=%d used_sources=%d/%d",
                len(answer),
                len(used_sources),
                len(grounded_sources),
            )
        return GlobalSearchResponseDTO(answer=answer, sources=used_sources)
