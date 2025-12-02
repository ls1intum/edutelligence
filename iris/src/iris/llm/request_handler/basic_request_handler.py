from typing import (
    Any,
    Callable,
    Dict,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
)

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.external.model import LanguageModel
from iris.llm.llm_manager import LlmManager
from iris.llm.request_handler.request_handler_interface import RequestHandler


class BasicRequestHandler(RequestHandler):
    """BasicRequestHandler is responsible for handling language model requests including text completion, chat,
    embedding, and semantic text splitting. It delegates operations to a language model via LlmManager.
    """

    model_id: str
    llm_manager: LlmManager = Field(default_factory=LlmManager)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def complete(
        self,
        prompt: str,
        arguments: CompletionArguments,
        image: Optional[ImageMessageContentDTO] = None,
    ) -> str:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.complete(prompt, arguments, image)

    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        message = llm.chat(messages, arguments, tools)
        message.token_usage.cost_per_million_input_token = (
            llm.cost_per_million_input_token
        )
        message.token_usage.cost_per_million_output_token = (
            llm.cost_per_million_output_token
        )
        return message

    def embed(self, text: str) -> list[float]:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
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
        llm = self.llm_manager.get_llm_by_id(self.model_id)

        return llm.split_text_semantically(
            text,
            breakpoint_threshold_type,
            breakpoint_threshold_amount,
            min_chunk_size,
        )

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """
        Binds a sequence of tools to the language model.

        Args:
            tools (Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]):
            A sequence of tools to be bound.

        Returns:
            LanguageModel: The language model with tools bound.
        """
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        llm.bind_tools(tools)
        return llm
