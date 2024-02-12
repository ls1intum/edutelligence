from domain import IrisMessage
from llm import RequestHandlerInterface, CompletionArguments
from llm.llm_manager import LlmManager
from llm.wrapper.abstract_llm_wrapper import (
    AbstractLlmCompletionWrapper,
    AbstractLlmChatCompletionWrapper,
    AbstractLlmEmbeddingWrapper,
)

type BasicRequestHandlerModel = str


class BasicRequestHandler(RequestHandlerInterface):
    model: BasicRequestHandlerModel
    llm_manager: LlmManager

    def __init__(self, model: BasicRequestHandlerModel):
        self.model = model
        self.llm_manager = LlmManager()

    def completion(self, prompt: str, arguments: CompletionArguments) -> str:
        llm = self.llm_manager.get_llm_by_id(self.model).llm
        if isinstance(llm, AbstractLlmCompletionWrapper):
            return llm.completion(prompt, arguments)
        else:
            raise NotImplementedError(
                f"The LLM {llm.__str__()} does not support completion"
            )

    def chat_completion(
        self, messages: list[IrisMessage], arguments: CompletionArguments
    ) -> IrisMessage:
        llm = self.llm_manager.get_llm_by_id(self.model).llm
        if isinstance(llm, AbstractLlmChatCompletionWrapper):
            return llm.chat_completion(messages, arguments)
        else:
            raise NotImplementedError(
                f"The LLM {llm.__str__()} does not support chat completion"
            )

    def create_embedding(self, text: str) -> list[float]:
        llm = self.llm_manager.get_llm_by_id(self.model).llm
        if isinstance(llm, AbstractLlmEmbeddingWrapper):
            return llm.create_embedding(text)
        else:
            raise NotImplementedError(
                f"The LLM {llm.__str__()} does not support embedding"
            )
