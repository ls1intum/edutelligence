from typing import Any, Callable, Dict, Literal, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from src.iris.common.pyris_message import PyrisMessage
from src.iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from src.iris.llm import LanguageModel
from src.iris.llm.completion_arguments import CompletionArguments
from src.iris.llm.llm_manager import LlmManager
from src.iris.llm.request_handler import RequestHandler


class BasicRequestHandler(RequestHandler):
    model_id: str
    llm_manager: LlmManager | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, model_id: str):
        super().__init__(model_id=model_id, llm_manager=None)
        self.model_id = model_id
        self.llm_manager = LlmManager()

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
        return llm.chat(messages, arguments, tools)

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
            text, breakpoint_threshold_type, breakpoint_threshold_amount, min_chunk_size
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
