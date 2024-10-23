from enum import Enum

from app.common.pyris_message import PyrisMessage
from app.llm.capability import RequirementList
from app.llm.external.model import (
    ChatModel,
    CompletionModel,
    EmbeddingModel,
    LanguageModel,
)
from app.llm.request_handler import RequestHandler
from app.llm.completion_arguments import CompletionArguments
from app.llm.llm_manager import LlmManager


class CapabilityRequestHandlerSelectionMode(Enum):
    """Enum for the selection mode of the capability request handler"""

    BEST = "best"
    WORST = "worst"


class CapabilityRequestHandler(RequestHandler):
    """Request handler that selects the best/worst model based on the requirements"""

    requirements: RequirementList
    selection_mode: CapabilityRequestHandlerSelectionMode
    llm_manager: LlmManager

    def __init__(
        self,
        requirements: RequirementList,
        selection_mode: CapabilityRequestHandlerSelectionMode = CapabilityRequestHandlerSelectionMode.WORST,
    ) -> None:
        self.requirements = requirements
        self.selection_mode = selection_mode
        self.llm_manager = LlmManager()

    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        llm = self._select_model(CompletionModel)
        return llm.complete(prompt, arguments)

    def chat(
        self, messages: list[PyrisMessage], arguments: CompletionArguments
    ) -> PyrisMessage:
        llm = self._select_model(ChatModel)
        message = llm.chat(messages, arguments)
        message.token_usage.cost_per_input_token = llm.capabilities.input_cost.value
        message.token_usage.cost_per_output_token = llm.capabilities.output_cost.value
        return message

    def embed(self, text: str) -> list[float]:
        llm = self._select_model(EmbeddingModel)
        return llm.embed(text)

    def _select_model(self, type_filter: type) -> LanguageModel:
        """Select the best/worst model based on the requirements and the selection mode"""
        llms = self.llm_manager.get_llms_sorted_by_capabilities_score(
            self.requirements,
            self.selection_mode == CapabilityRequestHandlerSelectionMode.WORST,
        )
        llms = [llm for llm in llms if isinstance(llm, type_filter)]

        if self.selection_mode == CapabilityRequestHandlerSelectionMode.BEST:
            llm = llms[0]
        else:
            llm = llms[-1]

        # Print the selected model for the logs
        print(f"Selected {llm.description}")
        return llm
