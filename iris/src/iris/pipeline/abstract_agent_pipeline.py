import logging
import traceback
from abc import ABC, abstractmethod
from threading import Thread
from typing import Any, Callable, Generic, List, Optional, TypeVar

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from memiris.domain.memory import Memory

from iris.common.memiris_setup import MemirisWrapper
from iris.common.message_converters import convert_iris_message_to_langchain_message
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.variant.abstract_variant import AbstractAgentVariant
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.shared.utils import generate_structured_tools_from_functions
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import StatusCallback

logger = logging.getLogger(__name__)

DTO = TypeVar("DTO")
VARIANT = TypeVar("VARIANT", bound=AbstractAgentVariant)


class AgentPipelineExecutionState(Generic[DTO, VARIANT]):
    """
    Represents the execution state of an agent pipeline.
    This class can be extended to include more details about the execution state.
    """

    db: VectorDatabase
    dto: DTO
    variant: VARIANT
    callback: StatusCallback
    memiris_wrapper: Optional[MemirisWrapper]
    memiris_memory_creation_thread: Optional[Thread]
    memiris_memory_creation_storage: list[Memory]
    message_history: list[PyrisMessage]
    tools: list[Callable]
    result: str
    llm: Any | None
    prompt: ChatPromptTemplate | None
    tokens: List[TokenUsageDTO]


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
    def is_memiris_memory_creation_enabled(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> bool:
        """Return True if background memory creation should be enabled for this run."""

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
        """Return a ChatPromptTemplate containing only messages before chat history."""

    @abstractmethod
    def get_memiris_tenant(self, dto: DTO) -> str:
        """Return the Memiris tenant identifier for the current user."""

    @abstractmethod
    def get_memiris_reference(self, dto: DTO):
        """Return the reference to use for the Memiris learnings created in this pipeline."""

    # ========================================
    # === CAN override (optional methods) ===
    # ========================================

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

    def get_agent_params(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> dict[str, Any]:
        """Return the parameter dict passed to the agent executor."""
        return {}

    def get_text_of_latest_user_message(
        self, state: AgentPipelineExecutionState[DTO, VARIANT]
    ) -> str:
        """
        Extract the latest user's text input from chat history.

        Subclasses may override this to pull from domain-specific DTOs or
        to support non-text inputs.

        Returns an empty string by default, which is safe for memory creation.
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

    def execute_agent(self, state: AgentPipelineExecutionState[DTO, VARIANT]) -> str:
        """
        Default agent execution: uses the LLM from state, prompt, tools and runs the agent loop.

        Subclasses customize behavior by implementing get_tools, build_system_message,
        get_agent_params, and using on_agent_step/post_agent_hook hooks.
        """

        params = self.get_agent_params(state)

        # Create and run agent using the LLM from state
        agent_executor, _ = self._create_agent_executor(
            llm=state.llm,
            prompt=state.prompt,
            tool_functions=state.tools,
        )
        output = self._run_agent_iterations(
            state=state, agent_executor=agent_executor, params=params
        )
        return output or ""

    def assemble_prompt_with_history(
        self, state: AgentPipelineExecutionState[DTO, VARIANT], system_prompt: str
    ) -> ChatPromptTemplate:
        """
        Combine the prefix prompt with converted chat history and add the agent scratchpad.

        Subclasses can override to customize how history is injected.
        """
        prefix_messages = [
            ("system", system_prompt.replace("{", "{{").replace("}", "}}"))
        ]
        history_lc_messages = [
            convert_iris_message_to_langchain_message(message)
            for message in state.message_history
        ]
        combined = (
            prefix_messages
            + history_lc_messages
            + [("placeholder", "{agent_scratchpad}")]
        )
        return ChatPromptTemplate.from_messages(combined)

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

    def on_agent_step(  # pylint: disable=unused-argument
        self, state: AgentPipelineExecutionState[DTO, VARIANT], step: dict[str, Any]
    ) -> None:
        """
        Optional hook called for every iteration step produced by the agent executor.
        Subclasses can override to implement token accounting, progress callbacks, etc.
        """
        # Default: no-op
        return

    # ================================================
    # === MUST NOT override (private/final methods) ===
    # ================================================

    def _create_agent_executor(
        self,
        llm: Any,
        prompt: ChatPromptTemplate,
        tool_functions: list[Callable],
    ) -> tuple[AgentExecutor, list[Any]]:
        """
        Build a structured-tool calling agent executor from an LLM, prompt and tool functions.

        Returns the executor and the structured tools used to initialize it.
        """
        tools = generate_structured_tools_from_functions(tool_functions)
        agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
        return agent_executor, tools

    def _run_agent_iterations(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        agent_executor: AgentExecutor,
        params: dict[str, Any],
    ) -> Optional[str]:
        """
        Execute the agent in streaming iteration mode and return the last output string.

        Calls on_agent_step for each step to allow subclasses to track tokens or progress.
        """
        final_output: Optional[str] = None
        for step in agent_executor.iter(params):
            # Track LLM tokens
            if hasattr(state, "llm") and state.llm and hasattr(state.llm, "tokens"):
                state.tokens.append(state.llm.tokens)

            # Allow subclasses to process each step
            try:
                self.on_agent_step(state, step)
            except Exception as exc:
                logger.exception("Exception in on_agent_step", exc_info=exc)
            if step.get("output") is not None:
                final_output = step["output"]
        return final_output

    def _create_session_title(
        self,
        state: AgentPipelineExecutionState[DTO, VARIANT],
        output: str,
        first_user_msg: str,
    ) -> Optional[str]:
        """
        Generate session title from the first user prompt and the model output.

        This is a common implementation used across different chat pipelines.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            first_user_msg: The first user message text

        Returns:
            The generated session title or None if not applicable
        """
        if not hasattr(self, "session_title_pipeline"):
            logger.warning(
                "session_title_pipeline not available, skipping title generation"
            )
            return None

        # Extract user language
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        try:
            if output:
                session_title = self.session_title_pipeline(
                    first_user_msg, output, user_language=user_language
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
            traceback.print_exc()
            return None

    def __call__(self, dto: DTO, variant: VARIANT, callback: StatusCallback):
        """
        Call the agent pipeline with the provided arguments.
        """
        # 0. Initialize the execution state
        state = AgentPipelineExecutionState[DTO, VARIANT]()
        state.dto = dto
        state.db = VectorDatabase()
        state.variant = variant
        state.callback = callback
        state.memiris_memory_creation_thread = None
        state.memiris_memory_creation_storage = []
        state.message_history = []
        state.tools = []
        state.result = ""
        state.llm = None
        state.prompt = None
        state.tokens = []
        state.memiris_wrapper = MemirisWrapper(
            state.db.client, self.get_memiris_tenant(state.dto)
        )

        # 1. Prepare message history, user query, LLM, prompt and tools
        state.message_history = self.get_recent_history_from_dto(state)
        user_query = self.get_text_of_latest_user_message(state)

        # Create LLM from variant's agent_model
        completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)
        state.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(
                version=state.variant.agent_model
            ),
            completion_args=completion_args,
        )

        system_message = self.build_system_message(state)
        state.prompt = self.assemble_prompt_with_history(
            state=state, system_prompt=system_message
        )
        state.tools = self.get_tools(state)

        # 4. Start memory creation if enabled
        if self.is_memiris_memory_creation_enabled(state):
            reference = self.get_memiris_reference(dto=state.dto)
            state.memiris_memory_creation_thread = (
                state.memiris_wrapper.create_memories_in_separate_thread(
                    user_query, reference, state.memiris_memory_creation_storage
                )
            )

        # 7.1. Run pre agent hook
        self.pre_agent_hook(state)

        # 7.2. Run the agent with the provided DTO
        state.result = self.execute_agent(state)

        # 7.3. Run post agent hook
        self.post_agent_hook(state)

        # 8. Wait for the memory creation to finish if enabled
        if state.memiris_memory_creation_thread:
            state.callback.in_progress("Waiting for memory creation to finish ...")
            # noinspection PyUnboundLocalVariable
            state.memiris_memory_creation_thread.join()
            state.callback.done(
                "Memory creation finished.",
                created_memories=state.memiris_memory_creation_storage,
            )
        else:
            state.callback.done("No memory creation thread started.")
