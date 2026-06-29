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
    HandoffDTO,
    HandoffType,
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

    def __init__(
        self,
        client: WeaviateClient,
        local: bool = False,
    ):
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
        access_context: AccessContext | None = None,
        prefetched_entities: list[GlobalSearchSourceDTO] | None = None,
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
        logger.debug("Intent classification | query=%r intent=%s", query[:80], intent)
        # Overfetch by 2x: a single lecture unit can fill multiple top slots with
        # different pages. Fetching more raw candidates gives the dedup step in
        # _merge_sources enough unique lecture units to fill the final limit.
        retrieval_limit = limit * 2
        if intent == SearchIntent.SKIP_AI:
            lecture_scored = self.retriever.search(
                query=query, limit=retrieval_limit, access_context=access_context
            )
            entity_sources = prefetched_entities or []
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

        # Step 2: Search lecture content; entity results come pre-fetched from Artemis
        lecture_scored: list[tuple[float, LectureSearchResultDTO]] = (
            self.retriever.search_with_vector_override(
                query=query,
                vector_text=hypothetical_answer,
                alpha=0.5,
                limit=retrieval_limit,
                access_context=access_context,
            )
        )
        entity_results: list[GlobalSearchSourceDTO] = prefetched_entities or []
        sources = self._merge_sources(lecture_scored, entity_results, limit)
        self._enrich_course_names(sources, run_id, base_url)

        # Fallback: if HyDE vector produced no hits (e.g. ambiguous query where HyDE
        # generated off-topic content), retry with the raw query embedding.
        if not sources:
            logger.info(
                "HyDE retrieval returned 0 sources — retrying with keyword-heavy search"
            )
            fallback_scored = self.retriever.search_with_vector_override(
                query=query,
                vector_text=query,
                alpha=0.1,
                limit=retrieval_limit,
                access_context=access_context,
            )
            sources = self._merge_sources(fallback_scored, entity_results, limit)
            self._enrich_course_names(sources, run_id, base_url)

        if not sources:
            return GlobalSearchResponseDTO(answer=None, sources=[])

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = sources

        def _type_label(s: GlobalSearchSourceDTO) -> str:
            # Lecture material stores a file-format source_type (e.g. "PDF"); present
            # it as the human-meaningful category instead. All other entities expose
            # their semantic type directly (channel, exercise, exam, faq).
            if s.lecture_unit is not None:
                return "lecture material"
            return s.source_type.replace("_", " ")

        def _location_label(s: GlobalSearchSourceDTO) -> str | None:
            if s.lecture_unit is not None:
                page = s.lecture_unit.page_number
                if page == -1:
                    meta = s.lecture_unit.display_meta or "video"
                    return f"Video @ {meta}"
                return f"Slide {page}"
            return None

        fallback = "this course"

        def _render(i: int, s: GlobalSearchSourceDTO) -> str:
            # TYPE is rendered first and always, regardless of snippet, so the model
            # can never confuse an entity's *name* (e.g. a channel called
            # "exercise-help") with its actual *type*.
            lines = [
                f"[{i + 1}] TYPE: {_type_label(s)}",
                f"COURSE: {s.course.name or fallback}",
                f"NAME: {s.title}",
            ]
            location = _location_label(s)
            if location:
                lines.append(f"LOCATION: {location}")
            if s.snippet:
                lines.append(f"CONTENT: {s.snippet}")
            return "\n".join(lines)

        context = "\n\n".join(_render(i, s) for i, s in enumerate(grounded_sources))
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

        handoff = self._determine_handoff(used_sources) if answer else None
        return GlobalSearchResponseDTO(
            answer=answer, sources=used_sources, handoff=handoff
        )

    @staticmethod
    def _determine_handoff(sources: list[GlobalSearchSourceDTO]) -> HandoffDTO | None:
        """Compute the most focused Iris chat context reachable from the used sources.

        Rules (evaluated top-down):
        - Sources from multiple courses → None (no single owner)
        - Exactly one exercise, nothing else → exercise chat
        - All sources from the same lecture → lecture chat
        - Everything else in a single course → course chat
        """
        if not sources:
            return None

        course_ids = {s.course.id for s in sources}
        if len(course_ids) > 1:
            return None

        course_id = next(iter(course_ids))
        exercise_sources = [s for s in sources if s.source_type == "exercise"]

        if len(exercise_sources) == 1 and len(sources) == 1:
            return HandoffDTO(
                type=HandoffType.EXERCISE,
                courseId=course_id,
                exerciseId=exercise_sources[0].entity_id,
            )

        lecture_sources = [s for s in sources if s.lecture is not None]
        if lecture_sources and not exercise_sources:
            lecture_ids = {s.lecture.id for s in lecture_sources}
            if len(lecture_ids) == 1:
                return HandoffDTO(
                    type=HandoffType.LECTURE,
                    courseId=course_id,
                    lectureId=next(iter(lecture_ids)),
                )

        return HandoffDTO(type=HandoffType.COURSE, courseId=course_id)

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
        """Deduplicate lecture chunks by unit, then RRF-merge with pre-fetched entities.

        Lecture retrieval returns one result per *page*, so a single lecture unit
        can fill multiple top slots with consecutive slides. We keep only the
        highest-scoring page per lecture unit before merging, ensuring diverse
        lecture units compete against entity results on equal footing.

        RRF handles score-scale differences between collections: lecture slides have
        dense text → higher raw scores; entity metadata is sparse → lower raw scores.
        Using rank position (not raw score) lets a top-ranked channel compete fairly
        against lower-ranked lecture slides.
        Formula: rrf_score = 1 / (k + rank), k=60 is the standard constant.
        """
        # Deduplicate: retriever returns results score-descending, so the first
        # occurrence of each lecture_unit.id is the best-scoring page for that unit.
        seen_unit_ids: set[int] = set()
        deduped: list[tuple[float, LectureSearchResultDTO]] = []
        for score, dto in lecture_scored:
            unit_id = dto.lecture_unit.id
            if unit_id not in seen_unit_ids:
                seen_unit_ids.add(unit_id)
                deduped.append((score, dto))

        converted: list[GlobalSearchSourceDTO] = [
            GlobalSearchSourceDTO.from_lecture_result(dto, score)
            for score, dto in deduped
        ]

        rrf_k = 60
        rrf: list[tuple[float, GlobalSearchSourceDTO]] = []
        for rank, src in enumerate(converted, start=1):
            rrf.append((1.0 / (rrf_k + rank), src))
        for rank, src in enumerate(entity_results, start=1):
            rrf.append((1.0 / (rrf_k + rank), src))
        rrf.sort(key=lambda x: x[0], reverse=True)
        merged = [src for _, src in rrf[:limit]]

        logger.info(
            "[GlobalSearch] merged sources=%d (lectures=%d→%d unique, entities=%d)  titles=%s",
            len(merged),
            len(lecture_scored),
            len(converted),
            len(entity_results),
            [f"[{s.source_type}] {s.title}({s.score:.3f})" for s in merged],
        )
        return merged
