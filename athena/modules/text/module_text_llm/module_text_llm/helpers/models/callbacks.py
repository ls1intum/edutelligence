from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import  LLMResult
from langchain_core.messages.ai import UsageMetadata

from athena import emit_meta, get_meta


class UsageHandler(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        meta = get_meta()
        
        total_usage = meta.get("total_usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        llm_calls = meta.get("llm_calls", [])

        for generations in response.generations:
            for generation in generations:
                message = generation.dict()["message"]
                generation_usage: UsageMetadata = message["usage_metadata"]
                model_name = message["response_metadata"].get("model_name", None)

                total_usage["input_tokens"] += generation_usage["input_tokens"]
                total_usage["output_tokens"] += generation_usage["output_tokens"]
                total_usage["total_tokens"] += generation_usage["total_tokens"]

                llm_calls.append({
                    "model_name": model_name,
                    "input_tokens": generation_usage["input_tokens"],
                    "output_tokens": generation_usage["output_tokens"],
                    "total_tokens": generation_usage["total_tokens"],
                })

        emit_meta("total_usage", total_usage)
        emit_meta("llm_calls", llm_calls)
