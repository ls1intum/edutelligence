from typing import Any, Callable, Dict, Literal, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from iris.common.logging_config import get_logger
from iris.common.pyris_message import PyrisMessage
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.external.model import (
    ChatModel,
    CompletionModel,
    EmbeddingModel,
    LanguageModel,
)
from iris.llm.llm_manager import LlmManager
from iris.llm.request_handler.request_handler_interface import RequestHandler

logger = get_logger(__name__)


class ModelVersionRequestHandler(RequestHandler):
    """Request handler that selects the first model with a matching version."""

    version: str
    llm_manager: LlmManager | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        version: str,
    ) -> None:
        super().__init__(
            version=version,
            llm_manager=None,
        )
        self.version = version
        self.llm_manager = LlmManager()

    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        llm = self._select_model(CompletionModel)
        return llm.complete(prompt, arguments)

    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        llm = self._select_model(ChatModel)
        message = llm.chat(messages, arguments, tools)
        message.token_usage.model_info = llm.model
        message.token_usage.cost_per_million_input_token = (
            llm.cost_per_million_input_token
        )
        message.token_usage.cost_per_million_output_token = (
            llm.cost_per_million_output_token
        )
        return message

    def embed(self, text: str) -> list[float]:
        llm = self._select_model(EmbeddingModel)
        return llm.embed(text)

    def split_text_semantically(
        self,
        text: str,
        breakpoint_threshold_type: Literal[
            "percentile", "standard_deviation", "interquartile", "gradient"
        ] = "gradient",
        breakpoint_threshold_amount: float = 95.0,
        min_chunk_size: int = 512,
    ):
        llm = self._select_model(EmbeddingModel)

        return llm.split_text_semantically(
            text,
            breakpoint_threshold_type,
            breakpoint_threshold_amount,
            min_chunk_size,
        )

    def _select_model(self, type_filter: type) -> LanguageModel:
        """Select the first model that matches the requested version"""
        # Get all LLMs from the manager
        all_llms = self.llm_manager.entries

        # Filter LLMs by type and model name
        matching_llms = [
            llm
            for llm in all_llms
            if isinstance(llm, type_filter) and llm.model == self.version
        ]

        if not matching_llms:
            raise ValueError(
                f"No {type_filter.__name__} found with model name {self.version}"
            )

        # Select the first matching LLM
        llm = matching_llms[0]

        logger.debug("Selected model | model=%s", llm.description)
        return llm

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """Bind the provided tools to the selected ChatModel.

        Args:
            tools: A sequence of tools to bind. Can be one of:
                - Dict[str, Any]: Tool configuration dictionary
                - Type[BaseModel]: Pydantic model class
                - Callable: Function to be used as a tool
                - BaseTool: LangChain tool instance

        Returns:
            LanguageModel: The selected chat model with tools bound

        Raises:
            ValueError: If tools sequence is empty or contains unsupported tool types
            TypeError: If selected model doesn't support tool binding
        """
        if not tools:
            raise ValueError("Tools sequence cannot be empty")

        llm = self._select_model(ChatModel)
        if not hasattr(llm, "bind_tools"):
            raise TypeError(
                f"Selected model {llm.description} doesn't support tool binding"
            )

        llm.bind_tools(tools)
        return llm
