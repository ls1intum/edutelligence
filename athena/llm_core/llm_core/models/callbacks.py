import os

from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import  LLMResult
from langchain_core.messages.ai import UsageMetadata

from athena import emit_meta, get_meta


class UsageHandler(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        cost_per_million_input_tokens = float(os.environ.get("LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN", 0.0))
        cost_per_million_output_tokens = float(os.environ.get("LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN", 0.0))

        meta = get_meta()
        
        total_usage = meta.get("totalUsage", {"numInputTokens": 0, "numOutputTokens": 0, "numTotalTokens": 0, "cost": 0 })
        llm_calls = meta.get("llmRequests", [])

        for generations in response.generations:
            for generation in generations:
                message = generation.dict()["message"]
                generation_usage: UsageMetadata = message["usage_metadata"]
                model_name = message["response_metadata"].get("model_name", None)

                total_usage["numInputTokens"] += generation_usage["input_tokens"]
                total_usage["numOutputTokens"] += generation_usage["output_tokens"]
                total_usage["numTotalTokens"] += generation_usage["total_tokens"]

                total_usage["cost"] += int(generation_usage["input_tokens"]) * cost_per_million_output_tokens / 1_000_000
                total_usage["cost"] += int(generation_usage["output_tokens"]) * cost_per_million_output_tokens / 1_000_000

                llm_calls.append({
                    "model": model_name,
                    "costPerMillionInputToken": cost_per_million_input_tokens,
                    "costPerMillionOutputToken": cost_per_million_output_tokens,
                    "numInputTokens": generation_usage["input_tokens"],
                    "numOutputTokens": generation_usage["output_tokens"],
                    "numTotalTokens": generation_usage["total_tokens"],
                })

        emit_meta("totalUsage", total_usage)
        emit_meta("llmRequests", llm_calls)
