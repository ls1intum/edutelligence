import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.search.lecture_search_dto import (
    AccessContext,
    GlobalSearchResponseDTO,
    GlobalSearchSourceDTO,
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
from iris.retrieval.searchable_entities_retrieval import SearchableEntitiesRetrieval
from iris.tracing import TracedThreadPoolExecutor, observe
from iris.web.status.status_update import get_course_names

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
        self.entity_retriever = SearchableEntitiesRetrieval(client, local=local)

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

        hyde_completion_args = CompletionArguments(
            reasoning_effort="none", max_tokens=150
        )
        answer_completion_args = CompletionArguments(
            response_format="JSON", reasoning_effort="none", max_tokens=600
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
        self,
        query: str,
        limit: int = 5,
        intent: SearchIntent | None = None,
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
        run_id: str | None = None,
        base_url: str | None = None,
        **_kwargs,
    ) -> GlobalSearchResponseDTO:
        """
        Answer a student's question using course content retrieved via HyDE.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :param intent: Pre-computed intent (SearchIntent). If None,
                       the classifier is called here.
        :param course_ids: Accessible course IDs resolved by Artemis. Passed as an opaque
                           filter to Weaviate — no access logic lives here.
        :return: An answer with source references.
        """
        # Guard: skip the full LLM pipeline for navigation queries
        if intent is None:
            intent = classify_intent(query)
        logger.info("Intent classification | query=%r intent=%s", query[:80], intent)
        if intent == SearchIntent.SKIP_AI:
            lecture_scored = self.retriever.search(
                query=query, limit=limit, access_context=access_context
            )
            # No HyDE on SKIP_AI path — both use raw query, scores are comparable
            entity_sources = self.entity_retriever.search(
                query=query, limit=limit, access_context=access_context
            )
            sources = self._merge_sources(lecture_scored, entity_sources, limit)
            self._enrich_course_names(sources, run_id, base_url)
            return GlobalSearchResponseDTO(answer=None, sources=sources)

        # Step 1: Generate a short hypothetical answer to use as the search vector
        hypothetical_answer = (self.hyde_prompt | self.hyde_pipeline).invoke(
            {"query": query}
        )
        self._append_tokens(
            self.hyde_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )
        logger.debug("HyDE hypothetical answer | output=%r", hypothetical_answer[:200])

        # Step 2: Search both lecture content and all other entities in parallel
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            lecture_future = executor.submit(
                self.retriever.search_with_vector_override,
                query=query,
                vector_text=hypothetical_answer,
                alpha=0.5,
                limit=limit,
                access_context=access_context,
            )
            entity_future = executor.submit(
                self.entity_retriever.search,
                query=query,
                limit=limit,
                access_context=access_context,
                vector_text=hypothetical_answer,
            )

        lecture_scored: list[tuple[float, LectureSearchResultDTO]] = (
            lecture_future.result()
        )
        entity_results: list[GlobalSearchSourceDTO] = entity_future.result()
        sources = self._merge_sources(lecture_scored, entity_results, limit)
        self._enrich_course_names(sources, run_id, base_url)

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

        if not sources:
            return GlobalSearchResponseDTO(answer=None, sources=[])

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            return GlobalSearchResponseDTO(answer=None, sources=[])

        def _location_label(s: GlobalSearchSourceDTO) -> str:
            if s.lecture_unit is not None:
                page = s.lecture_unit.page_number
                if page == -1:
                    meta = s.lecture_unit.display_meta or "video"
                    return f"Video @ {meta}"
                return f"Slide {page}"
            return s.source_type.replace("_", " ").title()

        fallback = "this course"
        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name or fallback} - {s.title}, {_location_label(s)}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
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
                fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", cleaned)
                parsed = json.loads(fixed)
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
                "[global-search] LLM refusal detected in answer text — suppressing to null"
            )
            answer = None

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )

        return GlobalSearchResponseDTO(answer=answer, sources=used_sources)

    @staticmethod
    def _enrich_course_names(
        sources: list[GlobalSearchSourceDTO],
        run_id: str | None,
        base_url: str | None,
    ) -> None:
        """Overwrite course.name on every source with the current title from Artemis.

        Only runs if run_id and base_url are provided. Fetches names for the unique
        course IDs in the final merged list — typically 1–5 IDs — so the DB hit is tiny.
        """
        if not sources or not run_id or not base_url:
            return
        unique_ids = list({s.course.id for s in sources})
        names = get_course_names(run_id, base_url, unique_ids)
        if not names:
            return
        for source in sources:
            if source.course.id in names:
                source.course.name = names[source.course.id]

    @staticmethod
    def _merge_sources(
        lecture_scored: list[tuple[float, LectureSearchResultDTO]],
        entity_results: list[GlobalSearchSourceDTO],
        limit: int,
    ) -> list[GlobalSearchSourceDTO]:
        """Score-based merge across both collections.
        Both retrievers use the same HyDE embedding on the LLM path, so scores are
        directly comparable. The top-limit results by score win regardless of source type.
        """
        converted: list[GlobalSearchSourceDTO] = [
            GlobalSearchSourceDTO.from_lecture_result(dto, score)
            for score, dto in lecture_scored
        ]

        # Reciprocal Rank Fusion: rank-based merging that handles score scale differences.
        # Raw hybrid scores are not comparable across collections (lecture slides have rich
        # text → higher scores; entity metadata is sparse → lower scores). RRF uses rank
        # position within each collection instead of raw score, so a top-ranked channel
        # competes fairly against lower-ranked lecture slides.
        # Formula: rrf_score = 1 / (k + rank),  k=60 is the standard constant.
        rrf_k = 60
        rrf: list[tuple[float, GlobalSearchSourceDTO]] = []
        for rank, src in enumerate(converted, start=1):
            rrf.append((1.0 / (rrf_k + rank), src))
        for rank, src in enumerate(entity_results, start=1):
            rrf.append((1.0 / (rrf_k + rank), src))
        rrf.sort(key=lambda x: x[0], reverse=True)
        merged = [src for _, src in rrf[:limit]]

        logger.info(
            "[GlobalSearch] merged sources=%d (lectures=%d, entities=%d)  titles=%s",
            len(merged),
            len(converted),
            len(entity_results),
            [f"[{s.source_type}] {s.title}({s.score:.3f})" for s in merged],
        )
        return merged
