import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.domain.search.lecture_search_dto import (
    LectureSearchAskRequestDTO,
    LectureSearchResultDTO,
)
from iris.domain.status.search_answer_status_update_dto import (
    SearchAnswerStatusUpdateDTO,
)
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.lecture_search_prompts import (
    answer_system_prompt,
    hyde_system_prompt,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline, InformationType
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.tracing import observe
from iris.web.status.status_update import SearchAnswerCallback

logger = get_logger(__name__)

# Matches [cite-loading:N] placeholders embedded by the answer LLM (1-based index)
_CITE_LOADING_INDEX_PATTERN = re.compile(r"\[cite-loading:(\d+)\]")

# Matches [cite-loading:any text] after index substitution, used to strip before citation pipeline
_CITE_LOADING_PATTERN = re.compile(r"\[cite-loading:[^\]]*\]")


class LectureSearchAnswerPipeline(SubPipeline):
    """
    Two-phase Ask Iris pipeline:

    Phase 1 (~3-4s): HyDE retrieval + answer generation. Posts plain answer with
    [cite-loading:keyword] skeleton markers to Artemis so the UI can render immediately.

    Phase 2 (~7-9s): CitationPipeline enriches the answer with full [cite:L:...] markers.
    Posts the cited answer to Artemis so inline citation bubbles replace the skeletons.

    HyDE (Hypothetical Document Embedding) improves retrieval precision by generating a
    short hypothetical answer first and embedding that instead of the raw question.
    Answer-space embeddings retrieve better matches than question-space embeddings.
    """

    hyde_llm: IrisLangchainChatModel
    answer_llm: IrisLangchainChatModel
    hyde_pipeline: Runnable
    answer_pipeline: Runnable

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="lecture_search_answer_pipeline")
        self.tokens = []
        self.retriever = LectureGlobalSearchRetrieval(client)
        self.citation_pipeline = CitationPipeline(local=local)

        pipeline_id = "lecture_search_answer_pipeline"
        hyde_model = resolve_model(pipeline_id, "default", "hyde", local=local)
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)

        self.hyde_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=hyde_model),
            completion_args=CompletionArguments(temperature=0.7),
        )
        self.answer_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=answer_model),
            completion_args=CompletionArguments(
                temperature=0.3, response_format="JSON"
            ),
        )
        hyde_pipeline = self.hyde_llm | StrOutputParser()
        answer_pipeline = self.answer_llm | StrOutputParser()

        hyde_prompt = ChatPromptTemplate.from_messages(
            [("system", hyde_system_prompt), ("user", "{query}")]
        )
        answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", answer_system_prompt),
                ("user", "Lecture content:\n{context}\n\nQuestion: {query}"),
            ]
        )

        # Store as composed chains so they can be mocked in tests
        self._hyde_chain = hyde_prompt | hyde_pipeline
        self._answer_chain = answer_prompt | answer_pipeline

    @observe(name="Lecture Search Answer Pipeline")
    def __call__(
        self,
        dto: LectureSearchAskRequestDTO,
        callback: SearchAnswerCallback,
        **_kwargs,
    ) -> None:
        """
        Run the two-phase Ask Iris pipeline and push both results to Artemis via callback.

        :param dto: Request containing query, limit, and Artemis callback coordinates.
        :param callback: Sends HTTP POSTs back to Artemis at phase 1 and phase 2.
        """
        # ── Phase 1: retrieve + generate answer ──────────────────────────────────────

        # Step 1: HyDE — embed a hypothetical answer for better retrieval
        hypothetical_answer = self._hyde_chain.invoke({"query": dto.query})
        self._append_tokens(
            self.hyde_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )
        logger.debug("HyDE output | %r", hypothetical_answer[:200])

        # Step 2: Retrieve using the hypothetical answer embedding
        sources: list[LectureSearchResultDTO] = (
            self.retriever.search_with_vector_override(
                query=dto.query,
                vector_text=hypothetical_answer,
                alpha=0.7,
                limit=dto.limit,
            )
        )

        if not sources:
            callback.send(
                SearchAnswerStatusUpdateDTO(
                    cited=False,
                    answer="No relevant course material was found for this query.",
                    sources=[],
                )
            )
            return

        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            callback.send(
                SearchAnswerStatusUpdateDTO(
                    cited=False,
                    answer="No relevant course material was found for this query.",
                    sources=[],
                )
            )
            return

        # Step 3: Generate answer with [cite-loading:N] skeleton markers
        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, Slide {s.lecture_unit.page_number}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        raw = self._answer_chain.invoke({"context": context, "query": dto.query})

        # Step 4: Parse structured JSON response
        try:
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            parsed = json.loads(cleaned)
            answer_with_indices = parsed.get("answer", raw)
            used_indices = {
                i - 1
                for i in parsed.get("used_sources", [])
                if isinstance(i, int) and i >= 1
            }
            used_sources = [
                s for i, s in enumerate(grounded_sources) if i in used_indices
            ]
        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            logger.warning("Failed to parse structured answer, using raw response")
            answer_with_indices = raw
            used_sources = grounded_sources

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_LECTURE_SEARCH_ANSWER_PIPELINE
        )

        # Step 5: Replace [cite-loading:N] indices with unit names
        # grounded_sources is 1-indexed in the LLM context, 0-indexed in the list
        answer_with_names = _CITE_LOADING_INDEX_PATTERN.sub(
            lambda m: _index_to_skeleton(m, grounded_sources),
            answer_with_indices,
        )

        # Phase 1 callback — plain answer with skeleton markers, cards available immediately
        callback.send(
            SearchAnswerStatusUpdateDTO(
                cited=False,
                answer=answer_with_names,
                sources=used_sources,
            )
        )

        if not used_sources:
            return

        # ── Phase 2: enrich with full citations ──────────────────────────────────────

        # Step 6: Strip skeleton markers → clean prose for CitationPipeline input
        clean_answer = _CITE_LOADING_PATTERN.sub("", answer_with_names).strip()

        # Step 7: Adapt used_sources to LectureRetrievalDTO (CitationPipeline expects this)
        retrieval_dto = _to_lecture_retrieval_dto(used_sources)

        # Step 8: Run CitationPipeline — adds [cite:L:unit_id:page:::keyword:summary] markers
        try:
            cited_answer = self.citation_pipeline(
                retrieval_dto,
                clean_answer,
                InformationType.PARAGRAPHS,
                variant="default",
                user_language="en",
            )
        except Exception as e:
            logger.error(
                "CitationPipeline failed, skipping phase 2 callback", exc_info=e
            )
            return

        # Phase 2 callback — answer with full inline citation markers
        callback.send(
            SearchAnswerStatusUpdateDTO(
                cited=True,
                answer=cited_answer,
                sources=used_sources,
            )
        )


def _index_to_skeleton(match: re.Match, sources: list[LectureSearchResultDTO]) -> str:
    """Replace [cite-loading:N] with [cite-loading:unit_name] using the sources list."""
    idx = int(match.group(1)) - 1  # convert 1-based LLM index to 0-based list index
    if 0 <= idx < len(sources):
        return f"[cite-loading:{sources[idx].lecture_unit.name}]"
    return ""  # out of range — remove the placeholder


def _to_lecture_retrieval_dto(
    sources: list[LectureSearchResultDTO],
) -> LectureRetrievalDTO:
    """
    Adapt global search results to the format CitationPipeline expects.

    Sources with a start_time (video segments) are mapped to LectureTranscriptionRetrievalDTO
    so CitationPipeline generates [cite:L:unit_id:page:start::keyword:summary] tags with a
    video timestamp. Sources without start_time (slide-only) map to
    LectureUnitPageChunkRetrievalDTO and produce page-only citation tags.
    """
    page_chunks = []
    transcriptions = []
    for s in sources:
        if not s.snippet:
            continue
        if s.lecture_unit.start_time is not None:
            transcriptions.append(
                LectureTranscriptionRetrievalDTO(
                    uuid="",
                    course_id=s.course.id,
                    course_name=s.course.name,
                    course_description="",
                    lecture_id=s.lecture.id,
                    lecture_name=s.lecture.name,
                    lecture_unit_id=s.lecture_unit.id,
                    lecture_unit_name=s.lecture_unit.name,
                    video_link="",
                    language="en",
                    segment_start_time=float(s.lecture_unit.start_time),
                    segment_end_time=None,
                    page_number=s.lecture_unit.page_number,
                    segment_summary=s.snippet,
                    segment_text=s.snippet,
                    base_url="",
                )
            )
        else:
            page_chunks.append(
                LectureUnitPageChunkRetrievalDTO(
                    uuid="",
                    course_id=s.course.id,
                    course_name=s.course.name,
                    course_description="",
                    lecture_id=s.lecture.id,
                    lecture_name=s.lecture.name,
                    lecture_unit_id=s.lecture_unit.id,
                    lecture_unit_name=s.lecture_unit.name,
                    lecture_unit_link=s.lecture_unit.link,
                    course_language="en",
                    page_number=s.lecture_unit.page_number,
                    page_text_content=s.snippet,
                    base_url="",
                )
            )
    return LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=transcriptions,
        lecture_unit_page_chunks=page_chunks,
    )
