"""
Tool providers for ChatPipeline.

Each provider function takes (state, context) and returns an Optional[Callable].
It checks context applicability, preconditions, resolves parameters from the DTO,
and calls the existing create_tool_* factory. Returns None if the tool is not
available for the given context/state.
"""

from typing import Callable, Optional

from iris.common.logging_config import get_logger
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.variant.chat_variant import ChatVariant
from iris.pipeline.abstract_agent_pipeline import AgentPipelineExecutionState
from iris.pipeline.chat.chat_context import ChatContext
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.tools import (
    create_tool_faq_content_retrieval,
    create_tool_file_lookup,
    create_tool_get_additional_exercise_details,
    create_tool_get_build_logs_analysis,
    create_tool_get_competency_list,
    create_tool_get_course_details,
    create_tool_get_exercise_list,
    create_tool_get_exercise_problem_statement,
    create_tool_get_feedbacks,
    create_tool_get_student_exercise_metrics,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)

logger = get_logger(__name__)

State = AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant]

# ---------------------------------------------------------------------------
# Course-related providers
# ---------------------------------------------------------------------------


def provide_course_details(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE, LECTURE, TEXT_EXERCISE"""
    if context not in {
        ChatContext.COURSE,
        ChatContext.LECTURE,
        ChatContext.TEXT_EXERCISE,
    }:
        return None
    return create_tool_get_course_details(state.dto.course, state.callback)


def provide_exercise_list(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE"""
    if context not in {ChatContext.COURSE}:
        return None
    if not state.dto.course:
        return None
    return create_tool_get_exercise_list(state.dto.course.exercises, state.callback)


def provide_exercise_problem_statement(
    state: State, context: ChatContext
) -> Optional[Callable]:
    """Available: COURSE"""
    if context not in {ChatContext.COURSE}:
        return None
    if not state.dto.course:
        return None
    return create_tool_get_exercise_problem_statement(
        state.dto.course.exercises, state.callback
    )


def provide_student_exercise_metrics(
    state: State, context: ChatContext
) -> Optional[Callable]:
    """Available: COURSE"""
    if context not in {ChatContext.COURSE}:
        return None
    return create_tool_get_student_exercise_metrics(state.dto.metrics, state.callback)


def provide_competency_list(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE"""
    if context not in {ChatContext.COURSE}:
        return None
    if not state.dto.course:
        return None
    return create_tool_get_competency_list(
        state.dto.course.competencies, state.dto.metrics, state.callback
    )


# ---------------------------------------------------------------------------
# Exercise-specific providers
# ---------------------------------------------------------------------------


def provide_submission_details(
    state: State, context: ChatContext
) -> Callable[[], dict] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    return create_tool_get_submission_details(
        state.dto.programming_exercise_submission, state.callback
    )


def provide_additional_exercise_details(
    state: State, context: ChatContext
) -> Callable[[], dict] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    if not state.dto.exercise:
        return None
    return create_tool_get_additional_exercise_details(
        state.dto.exercise, state.callback
    )


def provide_build_logs_analysis(
    state: State, context: ChatContext
) -> Callable[[], str] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    return create_tool_get_build_logs_analysis(
        state.dto.programming_exercise_submission, state.callback
    )


def provide_feedbacks(state: State, context: ChatContext) -> Callable[[], str] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    return create_tool_get_feedbacks(
        state.dto.programming_exercise_submission, state.callback
    )


def provide_repository_files(
    state: State, context: ChatContext
) -> Callable[[], str] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    if not state.dto.programming_exercise_submission:
        return None
    return create_tool_repository_files(
        state.dto.programming_exercise_submission.repository, state.callback
    )


def provide_file_lookup(
    state: State, context: ChatContext
) -> Callable[[str], str] | None:
    """Available: EXERCISE"""
    if context not in {ChatContext.EXERCISE}:
        return None
    if not state.dto.programming_exercise_submission:
        return None
    return create_tool_file_lookup(
        state.dto.programming_exercise_submission.repository, state.callback
    )


# ---------------------------------------------------------------------------
# Retrieval providers
# ---------------------------------------------------------------------------


def provide_lecture_retrieval(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE, LECTURE, EXERCISE, TEXT_EXERCISE"""
    if context not in {
        ChatContext.COURSE,
        ChatContext.LECTURE,
        ChatContext.EXERCISE,
        ChatContext.TEXT_EXERCISE,
    }:
        return None
    if not state.dto.course:
        return None

    course_id = state.dto.course.id
    if not should_allow_lecture_tool(state.db, course_id):
        return None
    lecture_retriever = LectureRetrieval(state.db.client)
    base_url = state.dto.settings.artemis_base_url if state.dto.settings else ""
    lecture_id = state.dto.lecture.id if state.dto.lecture else None
    lecture_unit_id = state.dto.lecture_unit_id if state.dto.lecture else None

    return create_tool_lecture_content_retrieval(
        lecture_retriever,
        course_id,
        base_url,
        state.callback,
        state.query_text,
        state.message_history,
        state.lecture_content_storage,
        lecture_id=lecture_id,
        lecture_unit_id=lecture_unit_id,
    )


def provide_faq_retrieval(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE, LECTURE, EXERCISE, TEXT_EXERCISE"""
    if context not in {
        ChatContext.COURSE,
        ChatContext.LECTURE,
        ChatContext.EXERCISE,
        ChatContext.TEXT_EXERCISE,
    }:
        return None
    if not (state.dto.course and state.dto.course.name):
        return None

    course_id = state.dto.course.id
    if not should_allow_faq_tool(state.db, course_id):
        return None
    faq_retriever = FaqRetrieval(state.db.client)

    return create_tool_faq_content_retrieval(
        faq_retriever,
        course_id,
        state.dto.course.name,
        state.dto.settings.artemis_base_url if state.dto.settings else "",
        state.callback,
        state.query_text,
        state.message_history,
        state.faq_storage,
    )


# ---------------------------------------------------------------------------
# Memiris providers
# ---------------------------------------------------------------------------


def provide_memory_search(state: State, context: ChatContext) -> Optional[Callable]:
    """Available: COURSE, LECTURE"""
    if context not in {ChatContext.COURSE, ChatContext.LECTURE}:
        return None
    if not (
        state.dto.user
        and state.dto.user.memiris_enabled
        and state.memiris_wrapper
        and state.memiris_wrapper.has_memories()
    ):
        return None
    return state.memiris_wrapper.create_tool_memory_search(
        state.accessed_memory_storage
    )


def provide_find_similar_memories(
    state: State, context: ChatContext
) -> Optional[Callable]:
    """Available: COURSE, LECTURE"""
    if context not in {ChatContext.COURSE, ChatContext.LECTURE}:
        return None
    if not (
        state.dto.user
        and state.dto.user.memiris_enabled
        and state.memiris_wrapper
        and state.memiris_wrapper.has_memories()
    ):
        return None
    return state.memiris_wrapper.create_tool_find_similar_memories(
        state.accessed_memory_storage
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CHAT_TOOL_PROVIDERS: list[Callable[[State, ChatContext], Optional[Callable]]] = [
    provide_lecture_retrieval,
    provide_faq_retrieval,
    provide_course_details,
    provide_exercise_list,
    provide_exercise_problem_statement,
    provide_student_exercise_metrics,
    provide_competency_list,
    provide_submission_details,
    provide_additional_exercise_details,
    provide_build_logs_analysis,
    provide_feedbacks,
    provide_repository_files,
    provide_file_lookup,
    provide_memory_search,
    provide_find_similar_memories,
]
