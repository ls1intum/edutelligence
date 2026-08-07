import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.common.timing import timed_span
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.status.activity_dto import ActivityDTO, ActivityKind
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.tools.chat_tool_providers import CHAT_TOOL_PROVIDERS
from iris.tracing import TracedThreadPoolExecutor, observe
from iris.web.status.status_update import StatusCallback

from ...common.memiris_setup import get_tenant_for_user
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from ...domain.variant.variant import Dep, Variant
from ...llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...llm.llm_configuration import LlmConfigurationError, resolve_model
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.mcq_generation_pipeline import McqGenerationPipeline
from ..shared.utils import datetime_to_string, format_custom_instructions
from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline
from .mcq_chat_mixin import (
    detect_mcq_intent,
    mcq_execute_agent,
    mcq_post_agent_hook,
    mcq_pre_agent_hook,
)

logger = get_logger(__name__)

_GUIDE_OK_SENTINEL = "!ok!"

_SUGGESTION_VARIANT: dict[IrisChatMode, str] = {
    IrisChatMode.COURSE: "course",
    IrisChatMode.EXERCISE: "exercise",
}


def _guide_response_is_ok(response: str) -> bool:
    return response.strip() == _GUIDE_OK_SENTINEL


class _GuideRefinementStreamHandler:
    """Buffer guide chunks until they can no longer be the ok sentinel."""

    def __init__(self, downstream: Callable[[Optional[str]], None]) -> None:
        self._downstream = downstream
        self._buffer = ""
        self._streaming = False

    def __call__(self, delta: Optional[str]) -> None:
        if delta is None:
            self._buffer = ""
            if self._streaming:
                self._downstream(None)
            return

        if self._streaming:
            self._downstream(delta)
            return

        self._buffer += delta
        if _GUIDE_OK_SENTINEL.startswith(self._buffer.strip()):
            return
        self._flush()

    def finish(self, final_text: str) -> None:
        if self._streaming:
            return
        if _guide_response_is_ok(final_text):
            self._buffer = ""
            return
        self._flush()

    def _flush(self) -> None:
        if self._buffer:
            self._downstream(self._buffer)
            self._buffer = ""
        self._streaming = True


def _support_level(dto: ChatPipelineExecutionDTO) -> str:
    # `settings` is Optional on the parent DTO, so the field default does
    # not apply.
    return dto.settings.support_level if dto.settings else "moderate"


def _dedup_by_uuid(items: list) -> list:
    """Return items de-duplicated by their ``uuid``, preserving order."""
    seen: set = set()
    result = []
    for item in items:
        if item.uuid not in seen:
            result.append(item)
            seen.add(item.uuid)
    return result


def _merge_lecture_content(
    current_view: Optional[LectureRetrievalDTO],
    retrieved: Optional[LectureRetrievalDTO],
) -> Optional[LectureRetrievalDTO]:
    """Merge the current-view content with the lecture tool's retrieved content.

    Either source may be ``None`` (no current view, or the agent never called the
    lecture retrieval tool). Items present in both (e.g. the current slide page
    also returned by RAG) are de-duplicated by uuid so they are not cited twice.
    """
    if current_view is None:
        return retrieved
    if retrieved is None:
        return current_view
    return LectureRetrievalDTO(
        lecture_unit_segments=_dedup_by_uuid(
            current_view.lecture_unit_segments + retrieved.lecture_unit_segments
        ),
        lecture_transcriptions=_dedup_by_uuid(
            current_view.lecture_transcriptions + retrieved.lecture_transcriptions
        ),
        lecture_unit_page_chunks=_dedup_by_uuid(
            current_view.lecture_unit_page_chunks + retrieved.lecture_unit_page_chunks
        ),
    )


def _tool_activity_snapshot(
    state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
) -> tuple[list[ActivityDTO], int]:
    activities, activity_seq = state.activity_tracker.authoritative_snapshot()
    return [item for item in activities if item.kind == ActivityKind.TOOL], activity_seq


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, Variant]):
    """
    Unified chat pipeline for course, exercise, text exercise, and lecture chat contexts.
    """

    PIPELINE_ID = "chat_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [
        ("default", "Default", "Uses a smaller model for faster responses."),
        ("advanced", "Advanced", "Uses a larger model, balancing speed and quality."),
    ]
    DEPENDENCIES = [
        Dep("citation_pipeline", variant="same"),
        Dep("session_title_generation_pipeline"),
        Dep("interaction_suggestion_pipeline", variant="course"),
        Dep("interaction_suggestion_pipeline", variant="exercise"),
        Dep("code_feedback_pipeline"),
        Dep("mcq_generation_pipeline"),
        Dep("lecture_retrieval_pipeline"),
        Dep("lecture_unit_segment_retrieval_pipeline"),
        Dep("lecture_transcriptions_retrieval_pipeline"),
        Dep("faq_retrieval_pipeline"),
    ]

    chat_mode: IrisChatMode
    event: Optional[str]
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    suggestion_pipeline: Optional[InteractionSuggestionPipeline]
    code_feedback_pipeline: Optional[CodeFeedbackPipeline]
    mcq_pipeline: McqGenerationPipeline
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any
    _guide_model_cache: dict[tuple[str, bool], str]

    def __init__(self, chat_mode: IrisChatMode, local: bool = False):
        """
        Initialize the exercise chat agent pipeline.
        """
        super().__init__(implementation_id=self.PIPELINE_ID)

        self.chat_mode = chat_mode

        self.event = None

        # Initialize pipelines & retrievers
        self.session_title_pipeline = SessionTitleGenerationPipeline(local=local)
        self.citation_pipeline = CitationPipeline(local=local)
        suggestion_variant = _SUGGESTION_VARIANT.get(self.chat_mode, "course")
        self.suggestion_pipeline = InteractionSuggestionPipeline(
            variant=suggestion_variant, local=local
        )
        self.code_feedback_pipeline = CodeFeedbackPipeline(
            local=local
        )  # TODO: Ungenutzt? Entfernen?
        self.mcq_pipeline = McqGenerationPipeline(local=local)

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        # Setup system prompt
        self.system_prompt_template = self.jinja_env.get_template(
            "chat_system_prompt.j2"
        )
        self.guide_prompt_template = self.jinja_env.get_template(
            "exercise_chat_guide_prompt.j2"
        )
        self._guide_model_cache = {}

    def __repr__(self):
        return f"{self.__class__.__name__}(context={self.chat_mode.value})"

    def __str__(self):
        return f"{self.__class__.__name__}(context={self.chat_mode.value})"

    def get_memiris_reference(self, dto: ChatPipelineExecutionDTO):
        """
        Return the reference to use for the Memiris learnings created in a programming exercise chat.
        It is simply the id of last user message in the chat history with a prefix.

        Returns:
            str: The reference identifier
        """
        last_message: Optional[PyrisMessage] = next(
            (
                m
                for m in reversed(dto.chat_history or [])
                if m.sender == IrisMessageRole.USER
            ),
            None,
        )
        return (
            f"session-messages/{last_message.id}"
            if last_message and last_message.id
            else "session-messages/unknown"
        )

    def get_memiris_tenant(self, dto: ChatPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Args:
            dto: The execution DTO containing user information.

        Returns:
            The tenant identifier string.
        """
        return get_tenant_for_user(dto.user.id)

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        step: dict[str, Any],
    ) -> None:
        """
        Handle each agent execution step.

        Args:
            state: The current pipeline execution state.
            step: The current step information.
        """
        del state, step

    def pre_agent_hook(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> None:
        """Spawn parallel MCQ generation thread if intent was detected."""
        if self.chat_mode not in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            return
        lecture_id = (
            state.dto.lecture.id if state.dto.lecture and state.dto.lecture.id else None
        )

        mcq_pre_agent_hook(
            state=state,
            mcq_pipeline=self.mcq_pipeline,
            get_text_of_latest_user_message=self.get_text_of_latest_user_message,
            db=state.db,
            course_id=state.dto.course.id,
            chat_history=state.dto.chat_history,
            lecture_id=lecture_id,
        )

    def execute_agent(self, state):
        """Use a direct LLM call when MCQ parallel is active, else default agent."""
        if getattr(state, "mcq_parallel", False):
            return mcq_execute_agent(state)
        return super().execute_agent(state)

    def should_stream_agent_response(
        self, state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant]
    ) -> bool:
        del state
        return self.chat_mode is not IrisChatMode.EXERCISE

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Process results after agent execution.

        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """
        try:
            result = state.result

            # If Programming Exercise, refine response using guide prompt
            if self.chat_mode == IrisChatMode.EXERCISE:
                with timed_span("ChatPipeline", "refine_response", state.start_time):
                    result = self._refine_response(state)

            # Add citations if applicable
            with timed_span("ChatPipeline", "citations", state.start_time):
                result = self._add_citations(state, result)
            state.result = result
            # Snapshot for title generation: the same post-citation, pre-MCQ
            # text the title was generated from before the deferral (the MCQ
            # JSON blob appended below must not leak into the title prompt).
            result_for_title = result

            # Handle MCQ placeholder replacement and parallel thread joining
            with timed_span("ChatPipeline", "mcq_join", state.start_time):
                mcq_post_agent_hook(
                    state=state,
                    mcq_pipeline=self.mcq_pipeline,
                    track_tokens=self._track_tokens,
                )

            result = state.result

            # Send the result first so the user sees the message immediately
            with timed_span("ChatPipeline", "final_result_callback", state.start_time):
                activities, activity_seq = _tool_activity_snapshot(state)
                state.callback.send_result(
                    result,
                    tokens=state.tokens,
                    accessed_memories=state.accessed_memory_storage,
                    activities=activities,
                    activity_seq=activity_seq,
                )
            logger.info(
                "Chat first result delivered | mode=%s elapsed_ms=%.0f",
                self.chat_mode.value,
                (time.perf_counter() - state.start_time) * 1000,
            )

            # The session title is not part of the answer, so it is generated
            # only after the final result was delivered. It reaches the client
            # with the next outgoing callback: the suggestions callback for
            # course/exercise chat, or the trailing callback sent by
            # AbstractAgentPipeline for the other modes.
            try:
                with timed_span("ChatPipeline", "session_title", state.start_time):
                    state.deferred_session_title = self._generate_session_title(
                        state, result_for_title, state.dto
                    )
            except Exception as e:
                logger.error("Error generating deferred session title", exc_info=e)

            # Generate and send suggestions separately (async from user's perspective)
            if self.chat_mode in [
                IrisChatMode.COURSE,
                IrisChatMode.EXERCISE,
            ]:
                with timed_span("ChatPipeline", "suggestions", state.start_time):
                    self._generate_suggestions(state, result)

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            activities, activity_seq = _tool_activity_snapshot(state)
            state.callback.fail(
                "Error in processing response",
                activities=activities,
                activity_seq=activity_seq,
                exception=e,
            )
            return state.result

    def prepare_state(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> None:
        """
        Pre-compute tool availability flags once, so both build_system_message
        and get_tools can read them without redundant DB calls.
        Also detects MCQ intent for COURSE and LECTURE modes.
        """
        dto = state.dto
        course_id = dto.course.id
        # The two availability checks are independent Weaviate round trips;
        # run them concurrently so the agent can start sooner.
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            lecture_tool_future = executor.submit(
                should_allow_lecture_tool, state.db, course_id
            )
            faq_tool_future = executor.submit(
                should_allow_faq_tool, state.db, course_id
            )
            state.allow_lecture_tool = lecture_tool_future.result()
            state.allow_faq_tool = faq_tool_future.result()
        state.allow_memiris_tool = bool(
            dto.user
            and dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )

        # Extract lecture contexts from DTO and store in state
        lecture_contexts = self._parse_lecture_context(dto)
        state.lecture_contexts = lecture_contexts

        state.query_text = self.get_text_of_latest_user_message(state)

        # Detect MCQ intent for modes that support it
        if self.chat_mode in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            is_mcq, count = detect_mcq_intent(state.query_text)
            if is_mcq:
                state.mcq_parallel = True
                state.mcq_count = count

    def get_tools(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Iterates over all registered tool providers and collects the ones
        whose required data is present in the current state.

        When MCQ parallel mode is active the agent only needs to write a
        short intro — no tools required.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        if getattr(state, "mcq_parallel", False):
            return []

        state.mcq_pipeline = self.mcq_pipeline

        tools: list[Callable] = []
        for provider in CHAT_TOOL_PROVIDERS:
            tool = provider(state)
            if tool is not None:
                tools.append(tool)
        return tools

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Build the system message/prompt for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            The system prompt string.
        """
        dto = state.dto

        query = self.get_latest_user_message(state)
        exercise = dto.programming_exercise or dto.text_exercise

        current_view_blocks = self._build_current_view(state)
        current_view_is_combined = any(
            getattr(ctx, "type", None) == "combinedView"
            for ctx in getattr(state, "lecture_contexts", []) or []
        )

        # Base template context (shared across all contexts)
        template_context: dict[str, Any] = {
            "chat_mode": self.chat_mode,
            "support_level": _support_level(dto),
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": dto.user.lang_key,
            "custom_instructions": format_custom_instructions(
                dto.custom_instructions or ""
            ),
            "course_name": dto.course.name,
            "allow_lecture_tool": state.allow_lecture_tool,
            "allow_faq_tool": state.allow_faq_tool,
            "allow_memiris_tool": state.allow_memiris_tool,
            "has_chat_history": bool(state.message_history),
            "has_exercises": bool(dto.course.exercises),
            "has_query": query is not None,
            "lecture_name": dto.lecture.title if dto.lecture else None,
            "current_view_blocks": current_view_blocks,
            "current_view_is_combined": current_view_is_combined,
            "exercise_title": exercise.title if exercise else "",
            "problem_statement": exercise.problem_statement if exercise else "",
            "programming_language": (
                dto.programming_exercise.programming_language.lower()
                if dto.programming_exercise
                and dto.programming_exercise.programming_language
                else ""
            ),
            "exercise_id": exercise.id if exercise else "",
            "start_date": (
                str(exercise.start_date) if exercise and exercise.start_date else ""
            ),
            "end_date": (
                str(exercise.end_date) if exercise and exercise.end_date else ""
            ),
            "text_exercise_submission": dto.text_exercise_submission,
            "mcq_parallel": getattr(state, "mcq_parallel", False),
            "event": self.event,
        }

        return self.system_prompt_template.render(template_context)

    def is_memiris_memory_creation_enabled(
        self, state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant]
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            True if memory creation should be enabled, False otherwise.
        """
        if self.chat_mode in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            return bool(state.dto.user.memiris_enabled)
        else:
            return False

    def _parse_lecture_context(self, dto: ChatPipelineExecutionDTO):
        """
        Parse lecture context from the DTO.

        Args:
            dto: The chat pipeline execution DTO.

        Returns:
            List of context objects (video/slides), or empty list if no context present
        """
        return dto.context if dto.context else []

    def _collect_context_positions(self, lecture_contexts):
        """Flatten slides/video contexts into page and timestamp position lists.

        Handles standalone ``slides``/``video`` entries as well as the
        ``slides``/``video`` nested inside a ``combinedView`` entry.

        Returns:
            A tuple of (context_pages, context_timestamps), where each entry is a
            dict describing the lecture unit and the page/timestamp being viewed.
        """
        context_pages = []
        context_timestamps = []

        def _add_slides(slides):
            context_pages.append(
                {"lecture_unit_id": slides.lecture_unit_id, "page": slides.page}
            )

        def _add_video(video):
            context_timestamps.append(
                {
                    "lecture_unit_id": video.lecture_unit_id,
                    "timestamp": video.timestamp,
                }
            )

        for context in lecture_contexts or []:
            if context.type == "slides":
                _add_slides(context)
            elif context.type == "video":
                _add_video(context)
            elif context.type == "combinedView":
                if context.slides is not None:
                    _add_slides(context.slides)
                if context.video is not None:
                    _add_video(context.video)

        return context_pages, context_timestamps

    def _get_lecture_retriever(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> LectureRetrieval:
        """Return a per-request LectureRetrieval instance, cached on the state.

        Both the prompt content injection and the lecture retrieval tool need a
        retriever; caching avoids instantiating it (and its models) twice.
        """
        retriever = getattr(state, "lecture_retriever", None)
        if retriever is None:
            retriever = LectureRetrieval(state.db.client)
            state.lecture_retriever = retriever
        return retriever

    def _build_current_view(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> list[str]:
        """Build the blocks describing where the student currently is.

        Looks up the slide page chunks / transcription segments for the student's
        current position and renders one block per position. Only positions whose
        material is ingested in the vector database are included — otherwise Iris
        can neither see nor retrieve the material and could not actually be
        context-aware about it.

        Only the position itself goes into the system prompt. The material at that
        position is put on the state for the current-position tool to read out
        instead: ending the prompt with that material makes it read like a finished
        answer, and a weaker model then answers straight from it without calling any
        tool at all — which also costs it the lecture retrieval and the point-out,
        since only retrieved results can be pointed at. Behind a tool the same
        material stays reachable, but the agent has to decide it wants it.

        The content is also stored in ``lecture_content_storage`` so answers about
        the current position get lecture citations even when the agent never calls
        the lecture retrieval tool.

        Returns:
            A list of position descriptions. Empty when there is no current position
            or none of the viewed material is ingested in the vector database.
        """
        context_pages, context_timestamps = self._collect_context_positions(
            getattr(state, "lecture_contexts", [])
        )
        if not context_pages and not context_timestamps:
            return []

        base_url = state.dto.settings.artemis_base_url if state.dto.settings else None
        page_chunks: list = []
        transcriptions: list = []
        try:
            page_chunks, transcriptions = self._get_lecture_retriever(
                state
            ).fetch_context_content(
                state.dto.course.id,
                base_url,
                context_pages=context_pages,
                context_timestamps=context_timestamps,
            )
        except Exception as e:
            logger.error("Error fetching current view lecture content", exc_info=e)

        # Only describe positions whose material is actually ingested in the
        # vector database: without content Iris can neither see nor retrieve the
        # material, so it cannot be context-aware about it. Listing such a
        # position would only invite bluffing about a page it has no access to.
        if not page_chunks and not transcriptions:
            return []

        names = {
            item.lecture_unit_id: item.lecture_unit_name
            for item in (*page_chunks, *transcriptions)
        }

        # Store the content under a dedicated key so answers about the current
        # position get citations even without a tool call. It is kept separate
        # from the lecture retrieval tool's "content" so the tool stays
        # completely independent of the viewing context; both are merged only
        # when citations are built (see _add_citations).
        state.lecture_content_storage["current_view"] = LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=list(transcriptions),
            lecture_unit_page_chunks=list(page_chunks),
        )

        # Group the page chunks by slide page so all chunks of one page are
        # bundled into a single block under that page's position description.
        chunks_by_page: dict[tuple, list] = {}
        for chunk in page_chunks:
            chunks_by_page.setdefault(
                (chunk.lecture_unit_id, chunk.page_number), []
            ).append(chunk)

        # Two parallel renderings of the same positions: the bare position for the prompt, and
        # the position with its material for the tool to read out on request.
        blocks: list[str] = []
        content_blocks: list[str] = []
        for p in context_pages:
            chunks = chunks_by_page.get((p["lecture_unit_id"], p["page"]))
            if not chunks:
                continue
            position = (
                f'The student is currently viewing page {p["page"]} of the lecture '
                f'slides of the lecture unit {names[p["lecture_unit_id"]]} '
                f'(lecture unit ID: {p["lecture_unit_id"]}).'
            )
            text = "\n".join(chunk.page_text_content for chunk in chunks)
            blocks.append(position)
            content_blocks.append(
                f"{position} The content of this slide:\n---\n{text}\n---"
            )
        for t in context_timestamps:
            segments = [
                tr
                for tr in transcriptions
                if tr.lecture_unit_id == t["lecture_unit_id"]
                and tr.segment_start_time <= t["timestamp"] < tr.segment_end_time
            ]
            if not segments:
                continue
            position = (
                f'The student is currently at {t["timestamp"]} seconds in the '
                f'lecture video of the lecture unit {names[t["lecture_unit_id"]]} '
                f'(lecture unit ID: {t["lecture_unit_id"]}).'
            )
            text = "\n".join(tr.segment_text for tr in segments)
            blocks.append(position)
            content_blocks.append(
                f"{position} The transcript at this point:\n---\n{text}\n---"
            )

        # Read by provide_current_view_content when the tools are built, which happens after
        # the system message.
        state.current_view_content_blocks = content_blocks

        return blocks

    def _add_citations(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        result: str,
    ) -> str:
        """
        Add citations to the response if applicable.

        Args:
            state: The current pipeline execution state.
            result: The current result string.

        Returns:
            The result with citations added.
        """

        try:
            # Add FAQ citations
            if state.faq_storage.get("faqs"):
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    state.faq_storage["faqs"],
                    result,
                    InformationType.FAQS,
                    variant=state.variant.id,
                    user_language=state.dto.user.lang_key,
                    base_url=base_url,
                )

            # Add lecture content citations. Merge the content the student is
            # currently viewing (stored before the agent ran) with whatever the
            # lecture retrieval tool retrieved, de-duplicating by uuid so the
            # same paragraph is not cited twice. Either source may be absent.
            lecture_content = _merge_lecture_content(
                state.lecture_content_storage.get("current_view"),
                state.lecture_content_storage.get("content"),
            )
            if lecture_content:
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    lecture_content,
                    result,
                    InformationType.PARAGRAPHS,
                    variant=state.variant.id,
                    user_language=state.dto.user.lang_key,
                    base_url=base_url,
                )

            # Track tokens from citation pipeline
            if (
                hasattr(self.citation_pipeline, "tokens")
                and self.citation_pipeline.tokens
            ):
                for token in self.citation_pipeline.tokens:
                    self._track_tokens(state, token)

            return result

        except Exception as e:
            logger.error("Error adding citations", exc_info=e)
            return result

    def _generate_session_title(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        output: str,
        dto: ChatPipelineExecutionDTO,
    ) -> Optional[str]:
        """
        Generate a session title from the latest user prompt and the model output.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            dto: The pipeline execution DTO

        Returns:
            The generated session title or None if not applicable
        """
        return self.update_session_title(state, output, dto.session_title)

    def _run_guide_refinement(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        response: str,
        stream_handler: Optional[Callable[[Optional[str]], None]] = None,
    ) -> tuple[str, str]:
        """
        Run the exercise guide refinement chain for a response.

        Args:
            state: The current pipeline execution state.
            response: The response text to check with the guide prompt.

        Returns:
            A tuple of the raw guide response and the response to use.
        """
        exercise = state.dto.programming_exercise or state.dto.text_exercise
        problem_statement = exercise.problem_statement if exercise else ""
        guide_prompt_rendered = self.guide_prompt_template.render(
            {
                "problem_statement": problem_statement,
                "support_level": _support_level(state.dto),
            }
        )

        completion_args = CompletionArguments(
            temperature=0.5,
            max_tokens=2000,
            stream_handler=stream_handler,
        )
        refinement_model = self._resolve_guide_model(state)
        llm_small = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=refinement_model),
            completion_args=completion_args,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=guide_prompt_rendered),
                HumanMessage(content=response),
            ]
        )

        guide_response = (prompt | llm_small | StrOutputParser()).invoke({})
        self._track_tokens(state, llm_small.tokens)

        if _guide_response_is_ok(guide_response):
            return guide_response, response
        return guide_response, guide_response

    def _resolve_guide_model(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Resolve the optional guide role model, falling back to chat for old configs.
        """
        cache = getattr(self, "_guide_model_cache", None)
        if cache is None:
            cache = {}
            self._guide_model_cache = cache

        cache_key = (state.variant.id, state.local)
        if cache_key in cache:
            return cache[cache_key]

        try:
            guide_model = resolve_model(
                self.PIPELINE_ID, state.variant.id, "guide", local=state.local
            )
        except LlmConfigurationError:
            guide_model = state.variant.model("chat", state.local)
            logger.info("guide role not configured — falling back to chat model")

        cache[cache_key] = guide_model
        return guide_model

    @observe(name="Response Refinement")
    def _refine_response(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Refine the agent response using the guide prompt. This is only available for programming exercises.

        Args:
            state: The current pipeline execution state.

        Returns:
            The refined response.
        """
        sender = None
        try:
            # Don't do anything if not programming exercise
            if self.chat_mode is not IrisChatMode.EXERCISE:
                return state.result

            guide_stream_handler = None
            sender = self._create_partial_result_sender(state)
            if sender is not None:
                sender.start()
                guide_stream_handler = _GuideRefinementStreamHandler(sender.on_delta)

            guide_response, refined_response = self._run_guide_refinement(
                state, state.result, stream_handler=guide_stream_handler
            )
            if guide_stream_handler is not None:
                guide_stream_handler.finish(guide_response)

            if _guide_response_is_ok(guide_response):
                logger.info("Response is ok and not rewritten")
                return refined_response
            logger.info("Response is rewritten")
            return refined_response

        except Exception as e:
            logger.warning("Error in refining response", exc_info=e)
            return state.result
        finally:
            if sender is not None:
                sender.stop()

    def _generate_suggestions(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        result: str,
    ) -> None:
        """
        Generate interaction suggestions. This is only available IrisChatMode.COURSE, IrisChatMode.EXERCISE.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
        if self.chat_mode not in {IrisChatMode.COURSE, IrisChatMode.EXERCISE}:
            return

        try:
            if result:
                suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                suggestion_dto.chat_history = state.dto.chat_history
                suggestion_dto.last_message = result
                suggestions = self.suggestion_pipeline(
                    suggestion_dto, user_language=state.dto.user.lang_key
                )

                if self.suggestion_pipeline.tokens is not None:
                    self._track_tokens(state, self.suggestion_pipeline.tokens)

                state.callback.send_suggestions(
                    suggestions,
                    session_title=state.deferred_session_title,
                )
                state.deferred_session_title_delivered = True
            else:
                logger.info(
                    "Skipping suggestion generation as no output was generated."
                )

        except Exception as e:
            logger.error("Error generating suggestions", exc_info=e)
            # The error callback terminates the job on the Artemis side, so a
            # later callback could not deliver the deferred title anymore —
            # attach it here so it is not lost.
            activities, activity_seq = _tool_activity_snapshot(state)
            # fail() marks the job terminal, so no later finish() can attach the
            # accumulated usage — carry state.tokens here so the FAILED status
            # still reports the answer/title tokens that were already produced.
            state.callback.fail(
                "Generating interaction suggestions failed.",
                session_title=state.deferred_session_title,
                activities=activities,
                activity_seq=activity_seq,
                tokens=state.tokens,
                exception=e,
            )
            state.deferred_session_title_delivered = True

    @observe(name="Chat Pipeline")
    def __call__(
        self,
        dto: ChatPipelineExecutionDTO,
        variant: Variant,
        callback: StatusCallback,
        event: str | None = None,
    ):
        """
        Execute the pipeline with the provided arguments.

        Args:
            dto: Execution data transfer object.
            variant: The variant configuration to use.
            callback: Status callback for progress updates.
            event: Optional event identifier (e.g. "jol").
        """
        try:
            logger.info("Running chat pipeline...")

            self.event = event

            # Delegate to parent class for standardized execution
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)

        except Exception as e:
            logger.error(
                "An error occurred while running the chat pipeline.", exc_info=e
            )
            callback.fail(
                "An error occurred while running the chat pipeline.",
                exception=e,
            )
