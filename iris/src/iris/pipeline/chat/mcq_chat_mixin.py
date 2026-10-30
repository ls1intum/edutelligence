"""Shared MCQ generation logic for chat pipelines.

Grounding content for the MCQ tool and the post-processing that puts the quiz the
agent generated into its answer (course and lecture chat).
"""

import json
from typing import Any, Optional

from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.pipeline.shared.citation_sources import strip_source_markers
from iris.pipeline.shared.mcq_generation_pipeline import McqGenerationPipeline
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.retrieval.lecture.lecture_visibility import (
    is_slide_visible,
    is_unit_released,
)
from iris.vector_database.instance_filter import artemis_instance_filter
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema

logger = get_logger(__name__)

_MCQ_CHUNK_PAGE_SIZE = 100
_MAX_MCQ_CANDIDATES = 10_000
_MAX_MCQ_VISIBLE_CHUNKS = 50
_MAX_MCQ_CONTENT_CHARS = 40_000


def retrieve_lecture_content_for_mcq(
    db: Any,
    course_id: int,
    base_url: str,
    lecture_id: Optional[int] = None,
    allow_lecture_tool: Optional[bool] = None,
) -> tuple[Optional[str], list[dict]]:
    """Fetch lecture unit page text directly from Weaviate for MCQ generation.

    Uses a simple filtered fetch instead of a search with reranking to keep
    MCQ generation fast.

    Args:
        db: The Weaviate database client wrapper.
        course_id: ID of the course.
        base_url: Artemis instance URL used to isolate colliding local IDs.
        lecture_id: Optional lecture ID to narrow results.
        allow_lecture_tool: Pre-computed lecture availability flag (e.g. from
            ``prepare_state``). Pass it to skip the redundant Weaviate check.

    Returns:
        Tuple of (formatted content string, list of lecture unit metadata dicts).
    """
    if allow_lecture_tool is None:
        allow_lecture_tool = should_allow_lecture_tool(db, course_id)
    if not allow_lecture_tool:
        return None, []
    try:
        chunk_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(course_id)
        chunk_filter &= artemis_instance_filter(LectureUnitPageChunkSchema, base_url)

        if lecture_id is not None:
            chunk_filter &= Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_ID.value
            ).equal(lecture_id)

        unit_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )
        unit_filter &= artemis_instance_filter(LectureUnitSchema, base_url)
        unit_results = db.lecture_units.query.fetch_objects(
            filters=unit_filter,
            limit=10_000,
            return_properties=[
                LectureUnitSchema.LECTURE_UNIT_ID.value,
                LectureUnitSchema.LECTURE_NAME.value,
                LectureUnitSchema.LECTURE_UNIT_NAME.value,
                LectureUnitSchema.RELEASE_DATE.value,
                LectureUnitSchema.BASE_URL.value,
            ],
        )
        unit_name_map: dict[tuple[str, int], dict] = {}
        for obj in unit_results.objects:
            props = obj.properties
            lu_id = props.get(LectureUnitSchema.LECTURE_UNIT_ID.value)
            unit_base_url = props.get(LectureUnitSchema.BASE_URL.value)
            if lu_id is not None and unit_base_url == base_url:
                unit_name_map[(unit_base_url, lu_id)] = {
                    "lecture_name": props.get(LectureUnitSchema.LECTURE_NAME.value, ""),
                    "unit_name": props.get(
                        LectureUnitSchema.LECTURE_UNIT_NAME.value, ""
                    ),
                    "released": is_unit_released(props),
                }

        content_parts: list[str] = []
        content_length = 0
        visible_chunk_count = 0
        units_data: dict[int, dict] = {}
        offset = 0
        while (
            offset < _MAX_MCQ_CANDIDATES
            and visible_chunk_count < _MAX_MCQ_VISIBLE_CHUNKS
            and content_length < _MAX_MCQ_CONTENT_CHARS
        ):
            page_limit = min(_MCQ_CHUNK_PAGE_SIZE, _MAX_MCQ_CANDIDATES - offset)
            chunks = db.lectures.query.fetch_objects(
                filters=chunk_filter,
                limit=page_limit,
                offset=offset,
                return_properties=[
                    LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                    LectureUnitPageChunkSchema.LECTURE_ID.value,
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                    LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value,
                    LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
                    LectureUnitPageChunkSchema.BASE_URL.value,
                ],
            )
            if not chunks.objects:
                break

            for obj in chunks.objects:
                props = obj.properties
                lu_id = props.get(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value)
                chunk_base_url = props.get(LectureUnitPageChunkSchema.BASE_URL.value)
                if chunk_base_url != base_url:
                    continue
                page = props.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value, 1)
                text = props.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value, "")
                names = unit_name_map.get((chunk_base_url, lu_id), {})
                if (
                    not text
                    or not names.get("released", False)
                    or not is_slide_visible(props)
                ):
                    continue
                lecture_name = names.get("lecture_name", "")
                unit_name = names.get("unit_name", "")
                fragment = (
                    f"Lecture: {lecture_name}, Unit: {unit_name}, "
                    f"Page {page}\n{text}\n\n"
                )
                remaining = _MAX_MCQ_CONTENT_CHARS - content_length
                fragment = fragment[:remaining]
                content_parts.append(fragment)
                content_length += len(fragment)
                visible_chunk_count += 1

                if lu_id is not None:
                    if lu_id not in units_data:
                        units_data[lu_id] = {
                            "lecture_unit_id": lu_id,
                            "lecture_name": lecture_name,
                            "unit_name": unit_name,
                            "pages": set(),
                        }
                    units_data[lu_id]["pages"].add(page)
                if (
                    visible_chunk_count >= _MAX_MCQ_VISIBLE_CHUNKS
                    or content_length >= _MAX_MCQ_CONTENT_CHARS
                ):
                    break

            offset += len(chunks.objects)
            if len(chunks.objects) < page_limit:
                break

        lecture_units_meta = []
        for data in units_data.values():
            pages = sorted(data["pages"])
            data["first_page"] = str(pages[0]) if pages else "1"
            del data["pages"]
            lecture_units_meta.append(data)

        content = "".join(content_parts)
        return (content if content.strip() else None), lecture_units_meta
    except Exception as e:
        logger.warning("Failed to fetch lecture summaries for MCQ: %s", str(e))
        return None, []


def _strip_stray_citations(mcq_json_str: str) -> str:
    """Strip any ``[cite:...]`` or ``[src:N]`` markers the LLM may have leaked into the MCQ JSON.

    Citations inside question text or answer options would confuse the client,
    so we remove them. The MCQ JSON is added after the answer's source markers were
    turned into cite blocks, so it has to be cleaned of both here. Code such as
    ``values[src:dst]`` stays as it is, like in the answer. The ``source`` field (if
    present) is also dropped since it is not consumed by the client.
    """
    try:
        parsed = json.loads(mcq_json_str)
    except (json.JSONDecodeError, TypeError):
        return mcq_json_str
    if not isinstance(parsed, dict):
        return mcq_json_str

    def _clean_question(q: dict) -> None:
        for opt in q.get("options", []):
            if "text" in opt:
                opt["text"] = strip_source_markers(opt["text"]).strip()
        if "question" in q:
            q["question"] = strip_source_markers(q["question"]).strip()
        if "explanation" in q:
            q["explanation"] = strip_source_markers(q["explanation"]).strip()
        q.pop("source", None)

    if parsed.get("type") == "mcq-set":
        for q in parsed.get("questions", []):
            _clean_question(q)
    elif parsed.get("type") == "mcq":
        _clean_question(parsed)

    return json.dumps(parsed)


def mcq_post_agent_hook(
    state: Any,
    mcq_pipeline: McqGenerationPipeline,
    track_tokens: Any,
) -> None:
    """Put the quiz the agent generated with the MCQ tool into ``state.result``.

    The tool returns a ``[MCQ_RESULT]`` placeholder; it is replaced with the quiz
    JSON (or the JSON is appended when the agent did not echo the placeholder).
    Must be called from the pipeline's ``post_agent_hook`` AFTER citations
    and title generation, but BEFORE ``callback.send_result()``.
    """
    mcq_storage = getattr(state, "mcq_result_storage", {})
    if mcq_storage.get("mcq_json"):
        mcq_json = _strip_stray_citations(mcq_storage["mcq_json"])
        if "[MCQ_RESULT]" in state.result:
            state.result = state.result.replace("[MCQ_RESULT]", mcq_json)
        else:
            state.result = state.result + "\n" + mcq_json
    for token in mcq_pipeline.tokens:
        track_tokens(state, token)
    mcq_pipeline.tokens.clear()
