import time
from abc import ABC, abstractmethod
from threading import Thread
from typing import Any, Callable, Generic, List, Optional, TypeVar

from iris.common.logging_config import get_logger
from iris.common.message_converters import normalize_history_message
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.reply_language import reply_language
from iris.common.timing import timed_span
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.compaction_dto import CompactionDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.status.activity_dto import ActivityKind
from iris.domain.status.suggested_context_dto import SuggestedContextDTO
from iris.domain.variant.abstract_variant import AbstractVariant
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.agent import AgentLoop, AgentTool
from iris.llm.iris_chat_model import IrisChatModel, message_text
from iris.llm.llm_manager import LlmManager
from iris.pipeline import Pipeline
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.pipeline.shared.citation_sources import CitationSourceRegistry
from iris.pipeline.shared.compaction import (
    CompactionSettings,
    ToolOutputBudget,
    compaction_boundary,
    compaction_instruction,
    fit_to_budget,
    get_compaction_settings,
    last_covered_excerpt,
    parse_summary,
    should_compact,
    split_history,
    summary_message_text,
    without_compactions,
)
from iris.tools.activity_metadata import curate_detail, curate_result
from iris.tracing import (
    TracingContext,
    clear_current_context,
    observe,
    set_current_context,
)
from iris.vector_database.database import VectorDatabase
from iris.watchdog import track_run, untrack_run
from iris.web.status.partial_result_sender import PartialResultSender
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)

DTO = TypeVar("DTO")
VARIANT = TypeVar("VARIANT", bound=AbstractVariant)


class AgentPipelineExecutionState(Generic[DTO, VARIANT]):
    """
    Represents the execution state of an agent pipeline.
    This class can be extended to include more details about the execution state.
    """

    db: VectorDatabase
    dto: DTO
    variant: VARIANT
    callback: StatusCallback
    message_history: list[PyrisMessage]
    tools: list[Callable]
    result: str
    llm: Any | None
    # The messages of the agent's first request: system prompt, optional summary,
    # history and the per-turn context. Built once per run.
    prompt_messages: list[PyrisMessage]
    tokens: List[TokenUsageDTO]
    local: bool
    tracing_context: Optional[TracingContext]
    query_text: str
    lecture_content_storage: dict
    # Material at the student's current viewing position, shared between the current-position tool
    # that reads it out and the point-out tool that invalidates it after moving the student.
    current_view_storage: dict
    faq_storage: dict
    allow_lecture_tool: bool
    allow_faq_tool: bool
    # perf_counter() timestamp of the run start, for latency span logging
    start_time: float
    # Session title generated after the final result was already delivered;
    # it is sent to the client with the next outgoing status callback.
    deferred_session_title: Optional[str]
    deferred_session_title_delivered: bool
    # Language of the final answer, resolved once so that title, suggestions and
    # citations agree. None until a pipeline resolves it.
    answer_language: Optional[str]
    # Context switch requested by the agent via the switch_chat_context tool;
    # delivered to Artemis with the final result status update.
    pending_context_switch: Optional[SuggestedContextDTO]
    # Sources the retrieval tools handed out ids for; None in pipelines without citations.
    citation_sources: Optional[CitationSourceRegistry]
    partial_result_sender: Optional[PartialResultSender]
    activity_tracker: ActivityTracker
    system_prompt: str
    # Auto-compaction: the model's size limits (None = fixed history window), the
    # newest stored summary, and the input size of the turn's first agent call.
    compaction_settings: Optional[CompactionSettings]
    compaction_summary: Optional[str]
    first_prompt_tokens: Optional[int]
    compaction_thread: Optional[Thread]
    compaction_holder: dict[str, Any]


def _filter_empty_messages(messages: list[PyrisMessage]) -> list[PyrisMessage]:
    """Filter out messages with no meaningful content before handing them to pipelines."""
    filtered: list[PyrisMessage] = []
    for msg in messages:
        if not msg.contents:
            continue
        content = msg.contents[0]
        if (
            isinstance(content, TextMessageContentDTO)
            and not content.text_content.strip()
        ):
            continue
        filtered.append(msg)
    return filtered


def _text_message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


class TrackerToolActivity:
    """Mirrors the agent loop's tool calls into the run's ActivityTracker."""

    def __init__(self, tracker: ActivityTracker):
        self._tracker = tracker

    def tool_started(self, name: str, arguments: dict) -> Optional[str]:
        try:
            return self._tracker.start(
                ActivityKind.TOOL, name, detail=curate_detail(name, arguments)
            )
        except Exception:
            logger.exception("Activity tracking failed during tool start")
            return None

    def tool_finished(self, handle: Optional[str], name: str, output: Any) -> None:
        if handle is None:
            return
        try:
            self._tracker.finish(handle, result=curate_result(name, output))
        except Exception:
            logger.exception("Activity tracking failed during tool end")

    def tool_failed(self, handle: Optional[str], name: str) -> None:
        del name
        if handle is None:
            return
        try:
            self._tracker.fail(handle)
        except Exception:
            logger.exception("Activity tracking failed during tool error")


def _model_capabilities(model_id: str) -> tuple[bool, bool]:
    """Whether the configured model takes strict tool schemas and tool_choice."""
    try:
        llm = LlmManager().get_llm_by_id(model_id)
    except Exception:  # configuration not loadable, e.g. in unit tests
        return False, True
    if llm is None:
        return False, True
    strict_tools = getattr(llm, "effective_strict_tools", False)
    supports_tool_choice = getattr(llm, "supports_tool_choice", True)
    return bool(strict_tools), bool(supports_tool_choice)


class AbstractAgentPipeline(ABC, Pipeline, Generic[DTO, VARIANT]):
    """
    Abstract base class for agent pipelines.

    Method categories:
    - MUST override: Required API a subclass must implement.
    - CAN override: Optional hooks/utilities to customize behavior.
    - MUST NOT override: Internal implementation methods (private with leading underscore or __call__).
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the agent pipeline.
        """
        super().__init__(*args, **kwargs)

    # ========================================
    # === MUST override (abstract methods) ===
    # ========================================

    @abstractmethod
    def get_tools(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> list[Callable]:
        """
        Get the tools available for the agent pipeline.

        Returns:
            list: A list of tools available for the agent pipeline.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

    @abstractmethod
    def build_system_message(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> str:
        """Return the system prompt: the part of the prompt that stays the same for a session."""

    def build_turn_context_message(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> Optional[str]:
        """
        Return context that changes from turn to turn (date, current view), or None.

        It is sent as a system message after the chat history, so the system prompt and
        the history stay a byte-identical prefix that the provider can read from its
        prompt cache on the next turn.
        """
        return None

    def get_token_pipeline(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> PipelineEnum:
        """Return the pipeline that the agent's own LLM calls are billed to."""
        return PipelineEnum.NOT_SET

    def supports_compaction(self) -> bool:
        """
        Return True if the run's callback can hand a compaction to Artemis.

        Compaction then runs for models with max_input_tokens in their config.
        """
        return False

    # ========================================
    # === CAN override (optional methods) ===
    # ========================================

    def create_tracing_context(self, dto: DTO, variant: VARIANT) -> TracingContext:
        """
        Create a TracingContext for this pipeline execution.

        Override this method to add pipeline-specific metadata like
        exercise IDs, lecture IDs, course names, etc.

        Default implementation extracts common fields from the DTO.
        """
        return TracingContext.from_dto(
            dto,
            pipeline_name=self.__class__.__name__,
            variant=variant.id if hasattr(variant, "id") else str(variant),
        )

    def _update_langfuse_trace(self, ctx: TracingContext) -> None:
        """
        Update the current LangFuse trace with metadata from the tracing context.

        This is called after setting up the tracing context to enrich the trace
        with user_id, session_id, course/exercise info, and other metadata.
        """
        try:
            # Use langfuse.get_client() which returns the decorator-aware global client
            import langfuse  # pylint: disable=import-outside-toplevel

            client = langfuse.get_client()
            if client:
                client.update_current_trace(**ctx.to_langfuse_params())
        except Exception as e:
            logger.debug("Failed to update LangFuse trace: %s", e)

    def _track_tokens(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        tokens: Optional[TokenUsageDTO],
    ) -> None:
        """
        Protected method for subclasses to track tokens from sub-pipelines.

        Args:
            state: The current pipeline execution state
            tokens: Token usage to track (can be None)
        """
        if tokens is not None:
            state.tokens.append(tokens)

    def _track_llm_usage(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> None:
        """
        Record the usage of the agent model's latest call, once.

        The chat model replaces its usage object on every call, so a step that made no
        new call still points at the previous call's usage.
        """
        usage = getattr(state.llm, "tokens", None) if state.llm else None
        if usage is None or any(tracked is usage for tracked in state.tokens):
            return
        usage.pipeline = self.get_token_pipeline(state)
        state.tokens.append(usage)
        if getattr(state, "first_prompt_tokens", None) is None:
            state.first_prompt_tokens = usage.num_input_tokens

    def get_text_of_latest_user_message(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> str:
        """
        Extract the latest user's text input from chat history.

        Subclasses may override this to pull from domain-specific DTOs or
        to support non-text inputs.

        Returns an empty string when the latest message has no text.
        """
        latest_user = self.get_latest_user_message(state)
        if (
            latest_user
            and latest_user.contents
            and isinstance(latest_user.contents[0], TextMessageContentDTO)
        ):
            return latest_user.contents[0].text_content
        return ""

    def get_history_limit(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> int:
        """
        Return how many of the most recent messages should be considered as history.
        Subclasses can override to narrow or expand context (default: 15).
        """
        return 15

    def should_stream_agent_response(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> bool:
        """Return True when the raw agent response may be streamed to the client."""
        _ = state
        return True

    def should_stream_agent_delta(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> bool:
        """Return True while text deltas of a streamed agent response may reach the client.

        Checked for every delta, so a pipeline can hold back the rest of the answer
        when the run changes course midway. Resets always pass, so the client can
        still clear a draft it already shows.
        """
        _ = state
        return True

    def get_recent_history_from_dto(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        limit: int | None = None,
    ) -> list[PyrisMessage]:
        """
        Return the last N messages from the DTO chat history (defaults to 15).
        """
        # TODO: Find a better way to get the history
        chat_history: list[PyrisMessage] = getattr(state.dto, "chat_history", []) or []
        effective_limit = limit if limit is not None else self.get_history_limit(state)
        return chat_history[-effective_limit:] if chat_history else []

    def get_latest_user_message(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> Optional[PyrisMessage]:
        """
        Return the most recent message sent by the USER, or None if not found.
        """
        for message in reversed(state.message_history):
            if message.sender == IrisMessageRole.USER:
                return message
        return None

    def get_max_agent_steps(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> int:
        """How many model calls with tools a run may make before it must answer."""
        return 15

    def execute_agent(self, state: AgentPipelineExecutionState[DTO, VARIANT]) -> str:
        """
        Default agent execution: runs the native agent loop with the run's model,
        prompt messages and tools.

        Subclasses customize behavior by implementing get_tools, build_system_message,
        build_turn_context_message, and the pre/post agent hooks.
        """
        result = self._run_agent_loop(state)
        return result or ""

    def build_prompt_messages(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        system_prompt: str,
        turn_context: Optional[str] = None,
    ) -> list[PyrisMessage]:
        """
        Combine the system prompt with the normalized chat history.

        Order: system prompt, the compaction summary (as a user message), the
        history, and the per-turn context last. Only the latest request carries
        the per-turn context, so the next turn shares everything up to the latest
        user message with the provider's prompt cache.
        Subclasses can override to customize how history is injected.
        """
        messages = [_text_message(IrisMessageRole.SYSTEM, system_prompt)]
        summary = getattr(state, "compaction_summary", None)
        if summary:
            # A user message, not a system message: the summary is built from student
            # messages and tool output, so it must not gain system authority.
            messages.append(
                _text_message(
                    IrisMessageRole.USER,
                    summary_message_text(self.sanitize_history_text(summary)),
                )
            )
        messages.extend(
            self._history_message(message) for message in state.message_history
        )
        if turn_context:
            messages.append(_text_message(IrisMessageRole.SYSTEM, turn_context))
        return messages

    def prepare_state(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> None:  # pylint: disable=unused-argument
        """
        Optional hook called once before build_system_message and get_tools.
        Subclasses should override this to pre-compute values that are needed
        by both methods (e.g. DB availability checks), so they are not duplicated.
        Default implementation is a no-op.
        """
        pass

    def pre_agent_hook(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> None:  # pylint: disable=unused-argument
        """
        Optional hook to run before the agent processes the DTO.
        This can be overridden by subclasses if needed.
        """
        pass

    def post_agent_hook(self, state: AgentPipelineExecutionState[DTO, VARIANT]) -> str:
        """
        Optional hook to run after the agent has processed the DTO.
        This can be overridden by subclasses if needed.
        """
        return state.result

    def sanitize_history_text(self, text: str) -> str:
        """
        Optional hook to clean earlier assistant answers and the compaction summary
        before they go back to the agent. Must be deterministic, so the cached
        prompt prefix stays identical across turns.
        """
        return text

    def sanitize_narration(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT], text: str
    ) -> str:
        """
        Optional hook to clean assistant text sent between tool calls; Artemis stores it.
        """
        return text

    def observe_model_input(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT], text: str
    ) -> None:
        """
        Optional hook that sees the text of every message the agent sends to the model in
        this run: the prompt messages and each tool result after output limits.
        """
        return

    def partial_text_transform(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> Optional[Callable[[str], str]]:
        """
        Optional hook that returns how a streamed draft is prepared before it is sent.
        """
        return None

    # ================================================
    # === MUST NOT override (private/final methods) ===
    # ================================================

    def _history_message(self, message: PyrisMessage) -> PyrisMessage:
        """A stored message as the model receives it, earlier answers cleaned."""
        normalized = normalize_history_message(message)
        if normalized.sender != IrisMessageRole.ASSISTANT:
            return normalized
        text = normalized.contents[0].text_content
        sanitized = self.sanitize_history_text(text)
        if sanitized == text:
            return normalized
        # A copy: the stored history (and a tool-call message's calls) stays as it is.
        return normalized.model_copy(
            update={"contents": [TextMessageContentDTO(textContent=sanitized)]}
        )

    def _run_agent_loop(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> Optional[str]:
        """
        Run the native agent loop and return the final answer text.

        Visible text the model writes next to its tool calls is sent to the student
        once, before the tools run. Each model call's usage is recorded right after
        the call, and tool runs are mirrored into the activity tracker.
        """
        emitted_intermediate_texts: set[str] = set()

        def emit_narration(text: str) -> None:
            text = self.sanitize_narration(state, text).strip()
            if not text or text in emitted_intermediate_texts:
                return
            emitted_intermediate_texts.add(text)
            send_intermediate = getattr(state.callback, "send_intermediate", None)
            if send_intermediate is None:
                return
            try:
                send_intermediate(text)
            except Exception as exc:
                logger.exception(
                    "Exception while sending intermediate message", exc_info=exc
                )

        model_id = getattr(getattr(state.llm, "request_handler", None), "model_id", "")
        strict_tools, supports_tool_choice = _model_capabilities(model_id)
        loop = AgentLoop(
            model=state.llm,
            tools=[AgentTool.from_function(tool) for tool in state.tools],
            max_steps=self.get_max_agent_steps(state),
            strict_tools=strict_tools,
            supports_tool_choice=supports_tool_choice,
            on_narration=emit_narration,
            on_tool_output=lambda text: self.observe_model_input(state, text),
            on_model_call=lambda: self._track_llm_usage(state),
            activity=TrackerToolActivity(state.activity_tracker),
        )
        for message in state.prompt_messages:
            for content in message.contents:
                if isinstance(content, TextMessageContentDTO) and content.text_content:
                    self.observe_model_input(state, content.text_content)
        result = loop.run(state.prompt_messages)
        logger.info(
            "Agent finished | steps=%d tool_calls=%d output_length=%d%s",
            result.steps,
            result.tool_calls,
            len(result.output),
            " (step limit reached)" if result.hit_step_limit else "",
        )
        return result.output

    def _load_history(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> list[PyrisMessage]:
        """
        Return the history for the agent prompt.

        SUMMARY messages are removed from the DTO, so side pipelines never see them.
        With compaction, the agent gets every message after the newest summary.
        Otherwise it gets the fixed window of recent messages.
        """
        chat_history: list[PyrisMessage] = getattr(state.dto, "chat_history", []) or []
        split = split_history(chat_history)
        if chat_history:
            state.dto.chat_history = without_compactions(chat_history)
        if state.compaction_settings is None:
            return self.get_recent_history_from_dto(state)
        state.compaction_summary = split.summary
        return fit_to_budget(
            split.messages, state.compaction_settings.history_budget_tokens
        )

    def _start_compaction(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        holder: dict[str, Any],
    ) -> Optional[Thread]:
        """
        Start a summary of the older history if this turn's prompt was too large.

        The request reuses the agent's system prompt, tools and history, so the
        provider reads most of it from the prompt cache. The result goes into holder.
        """
        settings = state.compaction_settings
        if settings is None or state.first_prompt_tokens is None:
            return None
        messages = state.message_history
        boundary = compaction_boundary(messages)
        if boundary is None:
            return None
        output_tokens = getattr(
            getattr(state.llm, "tokens", None), "num_output_tokens", 0
        )
        if not should_compact(
            state.first_prompt_tokens + output_tokens, settings, messages[:boundary]
        ):
            return None

        covers_through_message_id = messages[boundary - 1].id
        # Quoted from the answer as the model reads it in the history, cleaned the same way.
        instruction = compaction_instruction(
            last_covered_excerpt(self._history_message(messages[boundary - 1]))
        )
        model_id = state.llm.request_handler.model_id

        def run() -> None:
            try:
                llm = IrisChatModel(
                    request_handler=LlmRequestHandler(model_id=model_id),
                    completion_args=CompletionArguments(temperature=0.5),
                )
                strict_tools, supports_tool_choice = _model_capabilities(model_id)
                # Same tools as the agent request, so the provider reads the prefix
                # from its cache; tool_choice "none" forbids calls. A model that
                # ignores tool_choice gets no tools at all.
                tools = None
                tool_choice = None
                if state.tools and settings.send_tools and supports_tool_choice:
                    tools = [
                        AgentTool.from_function(tool).openai_schema(strict_tools)
                        for tool in state.tools
                    ]
                    tool_choice = "none"
                messages = self.build_prompt_messages(
                    state, state.system_prompt, turn_context=instruction
                )
                response = llm.chat(messages, tools, tool_choice=tool_choice)
                if llm.tokens is not None:
                    llm.tokens.pipeline = PipelineEnum.IRIS_CHAT_COMPACTION
                    holder["tokens"] = llm.tokens
                summary = parse_summary(message_text(response))
                if summary is None:
                    logger.warning("Compaction returned no summary; history kept")
                else:
                    holder["compaction"] = CompactionDTO(
                        summary=summary,
                        covers_through_message_id=covers_through_message_id,
                    )
                    logger.info(
                        "Compaction done | covers_through=%s summary_length=%d",
                        covers_through_message_id,
                        len(summary),
                    )
            except Exception as exc:
                logger.exception("Compaction failed", exc_info=exc)

        thread = Thread(target=run, name="iris-compaction", daemon=True)
        thread.start()
        return thread

    def _collect_compaction(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> Optional[CompactionDTO]:
        """
        Wait for the compaction of this turn and record its usage, once.

        Call it before any terminal callback: after one, Artemis accepts no more
        updates, so the usage and the summary would be lost.
        """
        thread = getattr(state, "compaction_thread", None)
        if thread is None:
            return None
        thread.join()
        state.compaction_thread = None
        self._track_tokens(state, state.compaction_holder.get("tokens"))
        return state.compaction_holder.get("compaction")

    def _create_partial_result_sender(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
    ) -> Optional[PartialResultSender]:
        if not getattr(getattr(state.dto, "settings", None), "stream_response", False):
            return None

        return PartialResultSender(
            state.callback.url,
            state.dto.settings.authentication_token,
            text_transform=self.partial_text_transform(state),
        )

    def _start_partial_result_sender(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
    ) -> Optional[PartialResultSender]:
        sender = self._create_partial_result_sender(state)
        if sender is None:
            return None

        sender.start()

        def stream_handler(delta: Optional[str]) -> None:
            if delta is None or self.should_stream_agent_delta(state):
                sender.on_delta(delta)

        state.llm.completion_args.stream_handler = stream_handler
        return sender

    def _collect_recent_messages(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        output: str,
    ) -> list[str]:
        """
        Collect the most recent messages from the chat history.

        Args:
            state: The current pipeline execution state
        Returns:
            list[str]: The most recent messages
        """
        window = state.message_history[-self.get_history_limit(state) :]  # noqa: E203
        # Drop everything up to and including the most recent context switch.
        # Messages before the switch describe the previous exercise/lecture and
        # would otherwise bias session-title generation toward the old topic.
        # The CTXSWAP marker itself is an instruction for the LLM, not a turn
        # worth titling, so it is excluded by slicing past it.
        last_switch = max(
            (
                i
                for i, msg in enumerate(window)
                if msg.sender == IrisMessageRole.CTXSWAP
            ),
            default=-1,
        )
        recent_messages: list[str] = []
        for msg in window[last_switch + 1 :]:  # noqa: E203
            if msg.contents and isinstance(msg.contents[0], TextMessageContentDTO):
                prefix = "User" if msg.sender == IrisMessageRole.USER else "Assistant"
                recent_messages.append(f"{prefix}: {msg.contents[0].text_content}")
        recent_messages.append(f"Assistant: {output}")
        return recent_messages

    def update_session_title(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        output: str,
        current_session_title: Optional[str],
    ) -> Optional[str]:
        """
        Updates session title if needed.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            current_session_title: The current session title
        Returns:
            Optional[str]: Updated session title or None if not applicable
        """
        session_title = (current_session_title or "").strip()
        recent_messages = self._collect_recent_messages(state, output)
        llm_out = self._create_session_title(
            state, session_title, recent_messages, output
        )

        text = str(llm_out).strip()

        if text == "KEEP":
            return None
        if text.startswith("UPDATE: "):
            new_title = text[len("UPDATE: ") :].strip()  # noqa: E203
            return new_title
        return None

    def _create_session_title(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        current_session_title: str,
        recent_messages: list[str],
        output: str,
    ) -> Optional[str]:
        """
        Generate a session title from the conversation history.

        This is a common implementation used across different chat pipelines.

        Args:
            state: The current pipeline execution state
            current_session_title: The current session title (might be empty)
            recent_messages: The most recent messages from the chat history
            output: The agent's output

        Returns:
            The generated session title or None if not applicable
        """
        if not hasattr(self, "session_title_pipeline"):
            logger.warning(
                "session_title_pipeline not available, skipping title generation"
            )
            return None

        # The title uses the language of the answer (using getattr for DTOs that
        # may not have the user or chat history attributes)
        language = getattr(state, "answer_language", None)
        if language is None:
            user = getattr(state.dto, "user", None)
            language = reply_language(
                output,
                getattr(state, "query_text", None),
                getattr(state.dto, "chat_history", None),
                getattr(user, "lang_key", None),
            )

        try:
            if output:
                session_title = self.session_title_pipeline(
                    current_session_title, recent_messages, language=language
                )
                if self.session_title_pipeline.tokens is not None:
                    self._track_tokens(state, self.session_title_pipeline.tokens)
                if session_title is None:
                    logger.error("Generating session title failed.")
                return session_title
            return None
        except Exception as e:
            logger.error(
                "An error occurred while running the session title generation pipeline",
                exc_info=e,
            )
            return None

    @observe(name="Abstract Agent Pipeline")
    def __call__(
        self, dto: DTO, variant: VARIANT, callback: StatusCallback, local: bool = False
    ):
        """
        Call the agent pipeline with the provided arguments.

        Args:
            dto: Data transfer object containing the request
            variant: The variant configuration to use
            callback: Status callback for updates
            local: If True, use local models; if False, use cloud models
        """
        start_time = time.perf_counter()
        pipeline_name = self.__class__.__name__

        logger.info(
            "Pipeline started | pipeline=%s variant=%s",
            pipeline_name,
            variant.id if hasattr(variant, "id") else "default",
        )

        # 0. Initialize the execution state
        state = AgentPipelineExecutionState[DTO, VARIANT]()
        # Bound before anything fallible runs: the run accumulates usage into the run-local state,
        # while a subclass' outer error path lives outside this method and can only reach
        # self.tokens. Both names point at the same list, so a run that dies mid-flight reports
        # what it spent up to that point, and never the leftovers of the instance's previous run.
        state.tokens = []
        self.tokens = state.tokens
        state.dto = dto
        state.db = VectorDatabase()
        state.variant = variant
        state.callback = callback
        state.message_history = []
        state.tools = []
        state.result = ""
        state.llm = None
        state.prompt_messages = []
        state.local = local  # Store local flag in state
        state.query_text = ""
        state.lecture_content_storage = {}
        state.current_view_storage = {}
        state.faq_storage = {}
        state.allow_lecture_tool = False
        state.allow_faq_tool = False
        state.start_time = start_time
        state.deferred_session_title = None
        state.answer_language = None
        state.deferred_session_title_delivered = False
        state.pending_context_switch = None
        state.citation_sources = None
        state.partial_result_sender = None
        state.system_prompt = ""
        state.compaction_settings = None
        state.compaction_summary = None
        state.first_prompt_tokens = None
        state.compaction_thread = None
        state.compaction_holder = {}
        state.activity_tracker = ActivityTracker(
            getattr(state.callback, "activity_snapshot", lambda _items, _seq: None)
        )
        state.tracing_context = self.create_tracing_context(dto, variant)

        # Set up LangFuse tracing context for this thread
        set_current_context(state.tracing_context)
        self._update_langfuse_trace(state.tracing_context)

        state.callback.update()

        track_run(callback)
        try:
            # 1. Select the model, then prepare history, user query, LLM, prompt and tools
            selected_version = state.variant.model("chat", local)
            if not selected_version:
                env = "local" if local else "cloud"
                raise ValueError(
                    f"Variant {state.variant.id} has empty chat model for {env}"
                )
            if self.supports_compaction():
                state.compaction_settings = get_compaction_settings(selected_version)

            state.message_history = _filter_empty_messages(self._load_history(state))

            # Create LLM from variant's model selection (local/cloud)
            completion_args = CompletionArguments(temperature=0.5)

            state.llm = IrisChatModel(
                request_handler=LlmRequestHandler(model_id=selected_version),
                completion_args=completion_args,
            )

            with timed_span(pipeline_name, "prepare_state", start_time):
                self.prepare_state(state)
            with timed_span(pipeline_name, "build_system_message", start_time):
                system_message = self.build_system_message(state)
                state.system_prompt = system_message
                turn_context = self.build_turn_context_message(  # pylint: disable=assignment-from-none
                    state
                )
            state.prompt_messages = self.build_prompt_messages(
                state=state, system_prompt=system_message, turn_context=turn_context
            )

            # Load tools for both local and cloud models
            with timed_span(pipeline_name, "build_tools", start_time):
                state.tools = self.get_tools(state)
                if state.compaction_settings is not None:
                    budget = ToolOutputBudget(
                        state.compaction_settings.tool_output_result_bytes,
                        state.compaction_settings.tool_output_turn_bytes,
                    )
                    state.tools = [budget.wrap(tool) for tool in state.tools]

            if local:
                logger.info("Using local model with tool calling support")
            else:
                logger.info("Using cloud model with tool calling support")

            # 7.1. Run pre agent hook
            self.pre_agent_hook(state)

            # 7.2. Run the agent with the provided DTO
            if self.should_stream_agent_response(state):
                state.partial_result_sender = self._start_partial_result_sender(state)
            try:
                with timed_span(pipeline_name, "agent_loop", start_time):
                    state.result = self.execute_agent(state)
            finally:
                if state.partial_result_sender is not None:
                    state.partial_result_sender.stop()

            # Runs next to the post agent hook, off the answer's path.
            state.compaction_thread = self._start_compaction(
                state, state.compaction_holder
            )

            # 7.3. Run post agent hook
            with timed_span(pipeline_name, "post_agent_hook", start_time):
                self.post_agent_hook(state)

            # A session title generated after the final result was sent still
            # needs to reach the client; attach it to the trailing callback.
            deferred_title = (
                None
                if state.deferred_session_title_delivered
                else state.deferred_session_title
            )

            # 8. Wait for compaction to finish if enabled
            finish_fields: dict[str, Any] = {}
            compaction = self._collect_compaction(state)
            if compaction is not None:
                finish_fields["compaction"] = compaction
            state.callback.finish(
                session_title=deferred_title,
                tokens=state.tokens,
                **finish_fields,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Pipeline completed | pipeline=%s | duration=%dms tools_used=%d",
                pipeline_name,
                duration_ms,
                len(state.tools),
            )
        finally:
            untrack_run(callback)
            # Clean up tracing context to prevent memory leaks
            clear_current_context()
