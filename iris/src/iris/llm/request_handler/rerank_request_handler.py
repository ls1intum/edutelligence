from typing import Any, Callable, Dict, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.llm import CompletionArguments, RequestHandler
from iris.llm.external.model import LanguageModel
from iris.llm.llm_manager import LlmManager


class RerankRequestHandler(RequestHandler):
    """RerankRequestHandler handles document reranking based on a query and a specified content field using a language
    model. It retrieves a language model from LlmManager and applies a reranking algorithm to reorder documents.
    """

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
        raise NotImplementedError

    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        raise NotImplementedError

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """Bind tools"""
        raise NotImplementedError

    def rerank(self, query, documents: [], top_n: int, content_field_name: str):
        if len(documents) == 0:
            return []
        mapped_responses = list(
            map(lambda x: getattr(x, content_field_name), documents)
        )

        cohere_client = self.llm_manager.get_llm_by_id(self.model_id)

        _, reranked_results, _ = cohere_client.rerank(
            query=query,
            documents=mapped_responses,
            top_n=top_n,
        )
        ranked_documents = []
        for result in reranked_results[1]:
            ranked_documents.append(documents[result.index])
        return ranked_documents
