from abc import ABC, abstractmethod
from threading import Thread
from typing import Callable, Generic, Optional, TypeVar

from memiris.domain.memory import Memory

from iris.common.memiris_setup import MemirisWrapper
from iris.common.pyris_message import PyrisMessage
from iris.vector_database.database import VectorDatabase
from iris.web.status.status_update import StatusCallback

DTO = TypeVar("DTO")
VARIANT = TypeVar(
    "VARIANT", bound="AbstractVariant"
)  # TODO: Define AbstractVariant class or interface


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
    memiris_memory_creation_thread = Optional[Thread]
    memiris_memory_creation_storage: list[Memory]
    message_history: list[PyrisMessage]
    tools: list[Callable]
    result: str


class AbstractAgentPipeline(ABC, Generic[DTO]):
    """
    Abstract base class for agent pipelines.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the agent pipeline.
        """
        pass

    @abstractmethod
    def is_memiris_memory_creation_enabled(self) -> bool:
        """
        Check if Memiris memory creation is enabled.

        Returns:
            bool: True if Memiris memory creation is enabled, False otherwise.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

    def get_memiris_tenant(self, dto: DTO) -> str:
        """
        Get the Memiris tenant for the user associated with the DTO.

        Args:
            dto (DTO): The data transfer object containing user information.

        Returns:
            str: The Memiris tenant for the user.
        """
        return "undefined"

    @abstractmethod
    def get_system_prompt(self, dto: DTO) -> str:
        """
        Get the system prompt for the agent pipeline.

        Returns:
            str: The system prompt for the agent pipeline.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

    @abstractmethod
    def get_tools(self, dto: DTO) -> list[Callable]:
        """
        Get the tools available for the agent pipeline.

        Returns:
            list: A list of tools available for the agent pipeline.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")

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

        # 1. Setup Memiris
        state.memiris_wrapper = MemirisWrapper(
            state.db.client, self.get_memiris_tenant(state.dto)
        )

        # 2. Get the tools available for the agent pipeline
        state.tools = self.get_tools(dto)

        # 3. Get the system prompt
        system_prompt = self.get_system_prompt(dto)

        # 4. Build message history
        state.message_history = []
        user_query = ""

        # 5. Setup agent
        # TODO: Implement agent setup logic in a separate method and call it here

        # 6. Start memory creation if enabled
        if self.is_memiris_memory_creation_enabled():
            state.memiris_memory_creation_storage = []
            state.memiris_memory_creation_thread = (
                state.memiris_wrapper.create_memories_in_separate_thread(
                    user_query, state.memiris_memory_creation_storage
                )
            )

        # 7.1. Run pre agent hook
        self.pre_agent_hook(state)

        # 7.2. Run the agent with the provided DTO
        # TODO: Implement agent execution logic in a separate method and call it here

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
