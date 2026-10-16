import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from iris.common.logging_config import get_logger
from iris.common.pyris_message import PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.llm import CompletionArguments, RequestHandler
from iris.llm.external.model import LanguageModel
from iris.llm.external.passthrough_reranker import PassthroughReranker
from iris.llm.llm_manager import LlmManager

logger = get_logger(__name__)

# After a failed rerank call, the same reranker is skipped for this long so that a
# down service does not add its timeout to every retrieval. It is then tried again:
# a single transient error must not switch reranking off until the next restart.
RERANK_FAILURE_COOLDOWN_SECONDS = 60.0

_cooldown_lock = threading.Lock()
_cooldown_until: dict[str, float] = {}


def _in_cooldown(model_id: str) -> bool:
    with _cooldown_lock:
        until = _cooldown_until.get(model_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            del _cooldown_until[model_id]
            return False
        return True


def _start_cooldown(model_id: str) -> None:
    with _cooldown_lock:
        _cooldown_until[model_id] = time.monotonic() + RERANK_FAILURE_COOLDOWN_SECONDS


def reset_rerank_cooldowns() -> None:
    """Forget all cooldowns (used by tests)."""
    with _cooldown_lock:
        _cooldown_until.clear()


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

    def rerank(self, query, documents: List, top_n: int, content_field_name: str):
        if not documents:
            return []
        valid_documents = [
            doc
            for doc in documents
            if doc is not None and getattr(doc, content_field_name, None) is not None
        ]
        if not valid_documents:
            return []

        # Skip a reranker that just failed, to avoid repeated timeout delays.
        # Passthrough behavior is identical here.
        if _in_cooldown(self.model_id):
            return valid_documents[:top_n]

        document_contents = list(
            map(lambda x: getattr(x, content_field_name), valid_documents)
        )

        reranker = self.llm_manager.get_llm_by_id(self.model_id)
        if reranker is None:
            # A missing config entry (typo'd id, or the entry commented out) is permanent,
            # not the transient failure the cooldown exists to back off from — conflating
            # the two hides a config error behind a generic "reranking failed" for the rest of
            # the process, with no lead pointing at the actual model_id that isn't configured.
            logger.warning(
                "No LLM entry configured for reranker model_id '%s'; returning top %d unranked documents.",
                self.model_id,
                top_n,
            )
            return valid_documents[:top_n]

        try:
            if isinstance(reranker, PassthroughReranker):
                # Its own, simpler contract (no network request): a plain list of indices,
                # not the RerankResponse every RerankModel provider normalizes to below.
                ranked_indices = reranker.rerank(
                    query=query,
                    documents=document_contents,
                    top_n=top_n,
                )
                return [valid_documents[index] for index in ranked_indices]

            response = reranker.rerank(
                query=query,
                documents=document_contents,
                top_n=top_n,
            )
            return [valid_documents[item.index] for item in response.results]
        except Exception as e:
            logger.warning(
                "Reranking with %s failed, skipping it for %.0f s. "
                "Returning top %d unranked documents: %s",
                self.model_id,
                RERANK_FAILURE_COOLDOWN_SECONDS,
                top_n,
                str(e),
            )
            _start_cooldown(self.model_id)
            return valid_documents[:top_n]
