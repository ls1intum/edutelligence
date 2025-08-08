from abc import ABC, abstractmethod
from threading import Thread
from typing import Any, Callable, Generic, Optional, TypeVar

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from memiris.domain.memory import Memory

from iris.common.memiris_setup import MemirisWrapper
from iris.common.message_converters import convert_iris_message_to_langchain_message
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.pipeline.shared.utils import generate_structured_tools_from_functions
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import StatusCallback

DTO = TypeVar("DTO")


class AbstractVariant(ABC):
    """Marker base class for pipeline variants."""


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
    memiris_wrapper: Optional[MemirisWrapper]
    memiris_memory_creation_thread: Optional[Thread]
    memiris_memory_creation_storage: list[Memory]
    message_history: list[PyrisMessage]
    tools: list[Callable]
    result: str
    llm: Any | None
    prompt: ChatPromptTemplate | None


class AbstractAgentPipeline(ABC, Generic[DTO]):
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
        pass

    # ========================================
    # === MUST override (abstract methods) ===
    # ========================================

    @abstractmethod
    def is_memiris_memory_creation_enabled(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> bool:
        """Return True if background memory creation should be enabled for this run."""

    @abstractmethod
    def get_tools(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> list[Callable]:
        """
        Get the tools available for the agent pipeline.

        Returns:
            list: A list of tools available for the agent pipeline.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

    @abstractmethod
    def create_llm(self, state: "AgentPipelineExecutionState[DTO, VARIANT]") -> Any:
        """Return the LLM to be used for this pipeline run."""

    @abstractmethod
    def build_system_message(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> str:
        """Return a ChatPromptTemplate containing only messages before chat history."""

    @abstractmethod
    def get_agent_params(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> dict[str, Any]:
        """Return the parameter dict passed to the agent executor."""

    @abstractmethod
    def get_memiris_tenant(self, dto: DTO) -> str:
        """Return the Memiris tenant identifier for the current user."""

    # ========================================
    # === CAN override (optional methods) ===
    # ========================================

    def get_text_of_latest_user_message(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
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

    def get_history_limit(
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> int:
        """
        Return how many of the most recent messages should be considered as history.
        Subclasses can override to narrow or expand context (default: 15).
        """
        return 15

    def get_recent_history_from_DTO(
        self,
        state: "AgentPipelineExecutionState[DTO, VARIANT]",
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
        self, state: "AgentPipelineExecutionState[DTO, VARIANT]"
    ) -> Optional[PyrisMessage]:
        """
        Return the most recent message sent by the USER, or None if not found.
        """
        for message in reversed(state.message_history):
            if message.sender == IrisMessageRole.USER:
                return message
        return None

    def execute_agent(self, state: "AgentPipelineExecutionState[DTO, VARIANT]") -> str:
        """
        Default agent execution: create LLM, prompt, tools and run the agent loop.

        Subclasses customize behavior by implementing create_llm, build_prompt,
        get_tools and get_agent_params, and using on_agent_step/post_agent_hook hooks.
        """
        
        params = self.get_agent_params(state)

        # Create and run agent
        agent_executor, _ = self._create_agent_executor(
            llm=state.llm, prompt=state.prompt, tool_functions=state.tools
        )
        output = self._run_agent_iterations(
            state=state, agent_executor=agent_executor, params=params
        )
        return output or ""

    def assemble_prompt_with_history(
        self,
        state: "AgentPipelineExecutionState[DTO, VARIANT]",
        system_prompt: str
    ) -> ChatPromptTemplate:
        """
        Combine the prefix prompt with converted chat history and add the agent scratchpad.

        Subclasses can override to customize how history is injected.
        """
        prefix_messages = [("system", system_prompt)]
        history_lc_messages = [
            convert_iris_message_to_langchain_message(message) for message in state.message_history
        ]
        combined = (
            prefix_messages
            + history_lc_messages
            + [("placeholder", "{agent_scratchpad}")]
        )
        return ChatPromptTemplate.from_messages(combined)

    def pre_agent_hook(self, state: AgentPipelineExecutionState[DTO, VARIANT]) -> None:
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

    def on_agent_step(
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
            # Allow subclasses to process each step (e.g., token accounting)
            try:
                self.on_agent_step(state, step)
            except Exception:
                # Swallow hook exceptions to avoid breaking agent loop
                pass
            if step.get("output") is not None:
                final_output = step["output"]
        return final_output

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
        state.memiris_wrapper = MemirisWrapper(
            state.db.client, self.get_memiris_tenant(state.dto)
        )


        # 1. Prepare message history, user query, LLM, prompt and tools
        state.message_history = self.get_recent_history_from_DTO(state)
        user_query = self.get_text_of_latest_user_message(state)

        state.llm = self.create_llm(state) # TODO: Move up? Variantensystem
        system_message = self.build_system_message(state)
        state.prompt = self.assemble_prompt_with_history(
            state=state, system_prompt=system_message
        )
        state.tools = self.get_tools(state)

        # 4. Start memory creation if enabled
        if self.is_memiris_memory_creation_enabled(state):
            state.memiris_memory_creation_thread = (
                state.memiris_wrapper.create_memories_in_separate_thread(
                    user_query, state.memiris_memory_creation_storage
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
