from app.domain import IrisMessage
from app.llm.request_handler import RequestHandler
from app.llm.completion_arguments import CompletionArguments
from app.llm.llm_manager import LlmManager


class BasicRequestHandler(RequestHandler):
    model_id: str
    llm_manager: LlmManager

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.llm_manager = LlmManager()

    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.complete(prompt, arguments)

    def chat(
        self, messages: list[IrisMessage], arguments: CompletionArguments
    ) -> IrisMessage:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.chat(messages, arguments)

    def embed(self, text: str) -> list[float]:
        llm = self.llm_manager.get_llm_by_id(self.model_id)
        return llm.embed(text)
