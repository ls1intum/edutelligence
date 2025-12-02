from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.llms import BaseLLM
from langchain_core.outputs import LLMResult
from langchain_core.outputs.generation import Generation
from pydantic import Field

from ...llm import CompletionArguments, RequestHandler


class IrisLangchainCompletionModel(BaseLLM):
    """Custom langchain chat model for our own request handler"""

    request_handler: RequestHandler = Field(...)
    max_tokens: Optional[int] = Field(default=None)

    def _generate(
        self,
        prompts: List[str],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> LLMResult:
        _ = run_manager  # Unused but required by interface
        _ = kwargs  # Unused but required by interface
        generations = []
        args = CompletionArguments(stop=stop, temperature=0.0)
        if self.max_tokens:
            args.max_tokens = self.max_tokens
        for prompt in prompts:
            completion = self.request_handler.complete(prompt=prompt, arguments=args)
            generations.append([Generation(text=completion)])
        return LLMResult(generations=generations)

    @property
    def _llm_type(self) -> str:
        return "Iris"
