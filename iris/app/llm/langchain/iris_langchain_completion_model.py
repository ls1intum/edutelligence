from typing import List, Optional, Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.llms import BaseLLM
from langchain_core.outputs import LLMResult
from langchain_core.outputs.generation import Generation

from llm import RequestHandler, CompletionArguments


class IrisLangchainCompletionModel(BaseLLM):
    """Custom langchain chat model for our own request handler"""

    request_handler: RequestHandler
    max_tokens: Optional[int] = None

    def __init__(self, request_handler: RequestHandler, **kwargs: Any) -> None:
        super().__init__(request_handler=request_handler, **kwargs)

    def _generate(
        self,
        prompts: List[str],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> LLMResult:
        generations = []
        args = CompletionArguments(stop=stop, temperature=0.0)
        if self.max_tokens:
            args.max_tokens = self.max_tokens
        for prompt in prompts:
            completion = self.request_handler.complete(prompt=prompt, arguments=args)
            generations.append([Generation(text=completion.choices[0].text)])
        return LLMResult(generations=generations)

    @property
    def _llm_type(self) -> str:
        return "Iris"
