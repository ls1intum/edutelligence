"""Shared MCQ generation logic for chat pipelines.

Provides detection, parallel execution, and post-processing of MCQ
questions used by both CourseChatPipeline and LectureChatPipeline.
"""

import json
import random
import re
from queue import Queue
from typing import Any, Optional

from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.pipeline.shared.mcq_generation_pipeline import McqGenerationPipeline
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema

logger = get_logger(__name__)

_PREPARING_MESSAGES = [
    "Preparing to generate questions...",
    "Getting your quiz ready...",
    "Setting up a challenge for you...",
    "Putting together some questions...",
]


_MAX_MCQ_COUNT = 10


def detect_mcq_intent(user_message: str) -> tuple[bool, int]:
    """Detect MCQ generation intent from user message.

    Only triggers on phrasing that clearly requests question *generation*,
    not on messages merely mentioning quizzes (e.g. "When is the quiz?").

    Returns:
        Tuple of (is_mcq_intent, question_count). Count defaults to 1.
    """
    message_lower = user_message.lower()

    # Check for explicit count + generation-intent patterns
    count_patterns = [
        r"(?:generate|create|give\s+me|make|prepare)\s+(\d+)\s*(?:more\s+)?(?:question|mcq|quiz)",
        r"(\d+)\s*(?:more\s+)?(?:question|mcq|quiz)\s+(?:about|on|for|from|regarding)",
        r"(?:another|more)\s+(\d+)\s*(?:question|mcq|quiz)",
    ]
    for pattern in count_patterns:
        match = re.search(pattern, message_lower)
        if match:
            count = max(1, min(int(match.group(1)), _MAX_MCQ_COUNT))
            return True, count

    # Keyword phrases that unambiguously request question generation
    mcq_keywords = [
        "quiz me",
        "multiple choice",
        "test me",
        "test my knowledge",
        "generate a question",
        "generate questions",
        "ask me a question",
        "ask me questions",
        "ask me some questions",
        "give me a question",
        "give me questions",
        "another question",
        "more questions",
        "one more",
    ]
    if any(kw in message_lower for kw in mcq_keywords):
        return True, 1

    return False, 0


def retrieve_lecture_content_for_mcq(
    db: Any,
    course_id: int,
    lecture_id: Optional[int] = None,
) -> tuple[Optional[str], list[dict]]:
    """Fetch lecture unit page text directly from Weaviate for MCQ generation.

    Uses a simple filtered fetch instead of the full RAG pipeline
    (query rewriting, HyDE, reranking) to keep MCQ generation fast.

    Args:
        db: The Weaviate database client wrapper.
        course_id: ID of the course.
        lecture_id: Optional lecture ID to narrow results.

    Returns:
        Tuple of (formatted content string, list of lecture unit metadata dicts).
    """
    if not should_allow_lecture_tool(db, course_id):
        return None, []
    try:
        chunk_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(course_id)

        if lecture_id is not None:
            chunk_filter &= Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_ID.value
            ).equal(lecture_id)

        chunks = db.lectures.query.fetch_objects(
            filters=chunk_filter,
            return_properties=[
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                LectureUnitPageChunkSchema.LECTURE_ID.value,
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value,
            ],
        )

        if not chunks.objects:
            return None, []

        unit_filter = Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
            course_id
        )
        unit_results = db.lecture_units.query.fetch_objects(
            filters=unit_filter,
            return_properties=[
                LectureUnitSchema.LECTURE_UNIT_ID.value,
                LectureUnitSchema.LECTURE_NAME.value,
                LectureUnitSchema.LECTURE_UNIT_NAME.value,
            ],
        )
        unit_name_map: dict[int, dict] = {}
        for obj in unit_results.objects:
            props = obj.properties
            lu_id = props.get(LectureUnitSchema.LECTURE_UNIT_ID.value)
            if lu_id is not None:
                unit_name_map[lu_id] = {
                    "lecture_name": props.get(LectureUnitSchema.LECTURE_NAME.value, ""),
                    "unit_name": props.get(
                        LectureUnitSchema.LECTURE_UNIT_NAME.value, ""
                    ),
                }

        content = ""
        units_data: dict[int, dict] = {}
        for obj in chunks.objects:
            props = obj.properties
            lu_id = props.get(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value)
            page = props.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value, 1)
            text = props.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value, "")
            names = unit_name_map.get(lu_id, {})
            lecture_name = names.get("lecture_name", "")
            unit_name = names.get("unit_name", "")

            if text:
                content += (
                    f"Lecture: {lecture_name}, Unit: {unit_name}, "
                    f"Page {page}\n{text}\n\n"
                )

            if lu_id is not None:
                if lu_id not in units_data:
                    units_data[lu_id] = {
                        "lecture_unit_id": lu_id,
                        "lecture_name": lecture_name,
                        "unit_name": unit_name,
                        "pages": set(),
                    }
                units_data[lu_id]["pages"].add(page)

        lecture_units_meta = []
        for data in units_data.values():
            pages = sorted(data["pages"])
            data["first_page"] = str(pages[0]) if pages else "1"
            del data["pages"]
            lecture_units_meta.append(data)

        return (content if content.strip() else None), lecture_units_meta
    except Exception as e:
        logger.warning("Failed to fetch lecture summaries for MCQ: %s", str(e))
        return None, []


def _strip_stray_citations(mcq_json_str: str) -> str:
    """Strip any ``[cite:...]`` markers the LLM may have leaked into the MCQ JSON.

    Citations inside question text or answer options would confuse the client,
    so we remove them.  The ``source`` field (if present) is also dropped since
    it is not consumed by the client.
    """
    try:
        parsed = json.loads(mcq_json_str)
    except (json.JSONDecodeError, TypeError):
        return mcq_json_str
    if not isinstance(parsed, dict):
        return mcq_json_str

    citation_re = re.compile(r"\[cite:[^\]]*\]")

    def _clean_question(q: dict) -> None:
        for opt in q.get("options", []):
            if "text" in opt:
                opt["text"] = citation_re.sub("", opt["text"]).strip()
        if "question" in q:
            q["question"] = citation_re.sub("", q["question"]).strip()
        if "explanation" in q:
            q["explanation"] = citation_re.sub("", q["explanation"]).strip()
        q.pop("source", None)

    if parsed.get("type") == "mcq-set":
        for q in parsed.get("questions", []):
            _clean_question(q)
    elif parsed.get("type") == "mcq":
        _clean_question(parsed)

    return json.dumps(parsed)


def mcq_pre_agent_hook(
    state: Any,
    mcq_pipeline: McqGenerationPipeline,
    get_text_of_latest_user_message: Any,
    db: Any,
    course_id: int,
    chat_history: Any,
    lecture_id: Optional[int] = None,
) -> None:
    """Spawn parallel MCQ generation thread if intent was detected.

    Sets ``mcq_thread`` and ``mcq_result_storage`` on *state*.
    """
    if not getattr(state, "mcq_parallel", False):
        return

    state.callback.in_progress(
        "Preparing quiz...",
        chat_message=random.choice(_PREPARING_MESSAGES),  # nosec B311
    )

    if not hasattr(state, "mcq_result_storage"):
        setattr(state, "mcq_result_storage", {})

    user_language = "en"
    if state.dto.user and state.dto.user.lang_key:
        user_language = state.dto.user.lang_key

    user_message = get_text_of_latest_user_message(state)
    count = getattr(state, "mcq_count", 1)

    lecture_content, _ = retrieve_lecture_content_for_mcq(
        db, course_id, lecture_id=lecture_id
    )

    setattr(
        state,
        "mcq_thread",
        mcq_pipeline.run_in_thread(
            command=user_message,
            chat_history=chat_history,
            user_language=user_language,
            result_storage=getattr(state, "mcq_result_storage", {}),
            count=count,
            lecture_content=lecture_content,
        ),
    )


def mcq_execute_agent(state: Any) -> str:
    """Generate a short intro message for the MCQ quiz via a direct LLM call.

    Bypasses the full agent loop (which can waste time calling tools) since
    the only job is to write 1-2 sentences acknowledging the quiz request.
    """
    messages = state.prompt.format_messages(agent_scratchpad=[])
    response = state.llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    logger.info("MCQ intro generated via direct LLM call | length=%d", len(content))
    return content


def mcq_post_agent_hook(
    state: Any,
    mcq_pipeline: McqGenerationPipeline,
    track_tokens: Any,
    timeout: int = 180,
) -> None:
    """Join the parallel MCQ thread and append results to ``state.result``.

    Handles both single-question and multi-question (mcq-set) modes.
    Must be called from the pipeline's ``post_agent_hook`` AFTER citations
    and title generation, but BEFORE ``callback.done()``.
    """
    mcq_thread = getattr(state, "mcq_thread", None)
    mcq_parallel = getattr(state, "mcq_parallel", False)
    mcq_count = getattr(state, "mcq_count", 1)

    # Non-parallel path (tool-calling fallback): replace placeholder inline
    if not mcq_parallel:
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
        return

    # Parallel path: join thread and collect results
    if not mcq_thread:
        return

    state.callback.in_progress(
        "Generating questions...",
        chat_message="Generating questions...",
    )

    mcq_thread.join(timeout=timeout)
    if mcq_thread.is_alive():
        logger.error("MCQ generation thread did not finish within timeout")

    mcq_storage = getattr(state, "mcq_result_storage", {})
    mcq_queue: Optional[Queue] = mcq_storage.get("queue")

    if mcq_storage.get("error"):
        logger.error("MCQ thread reported error: %s", mcq_storage["error"])

    if mcq_count == 1:
        found_mcq = False
        if mcq_queue:
            while not mcq_queue.empty():
                msg_type, data = mcq_queue.get_nowait()
                if msg_type == "mcq":
                    data = _strip_stray_citations(data)
                    state.result = state.result + "\n" + data
                    found_mcq = True
                elif msg_type == "error":
                    logger.error("MCQ generation error: %s", data)
        if not found_mcq:
            logger.warning("No MCQ was produced by the parallel thread")
            state.result += (
                "\n\nSorry, I was unable to generate the question. " "Please try again."
            )
    else:
        collected_questions: list[dict] = []
        if mcq_queue:
            while not mcq_queue.empty():
                msg_type, data = mcq_queue.get_nowait()
                if msg_type == "mcq":
                    try:
                        data = _strip_stray_citations(data)
                        parsed = json.loads(data)
                        if parsed.get("type") == "mcq-set":
                            collected_questions.extend(parsed.get("questions", []))
                        else:
                            collected_questions.append(parsed)
                    except json.JSONDecodeError:
                        logger.error("Invalid MCQ JSON received: %s", data)
                elif msg_type == "error":
                    logger.error("MCQ generation error for multi-question: %s", data)
        if collected_questions:
            mcq_set = json.dumps(
                {
                    "type": "mcq-set",
                    "questions": collected_questions[:mcq_count],
                }
            )
            state.result = state.result + "\n" + mcq_set
        else:
            logger.warning(
                "No MCQ questions collected for mcq-set (requested %d)",
                mcq_count,
            )
            state.result += (
                "\n\nSorry, I was unable to generate the questions. "
                "Please try again."
            )

    if not mcq_thread.is_alive():
        for token in mcq_pipeline.tokens:
            track_tokens(state, token)
        mcq_pipeline.tokens.clear()
