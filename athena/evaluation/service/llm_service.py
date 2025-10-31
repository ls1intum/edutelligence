import string
from typing import List, Any

from langchain_community.callbacks import get_openai_callback
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from model.evaluation_model import MetricEvaluations


def evaluate_feedback_with_model(
    prompt: List[BaseMessage],
    model: AzureChatOpenAI,
    submission_id: int,
    feedback_type: string,
) -> dict[str, Any] | None:
    with get_openai_callback() as cb:
        response = model.invoke(
            prompt, max_tokens=100, logprobs=True, top_logprobs=5, temperature=0
        )

        output_parser = PydanticOutputParser(pydantic_object=MetricEvaluations)

        try:
            parsed_response = output_parser.parse(response.content)
        except ValidationError as e:
            print(f"Response validation failed: {e}")
            return None

        flattened_eval = {}
        for metric_eval in parsed_response.evaluations:
            flattened_eval[f"{metric_eval.title}_score"] = metric_eval.score

        flattened_eval.update(
            {
                "submission_id": submission_id,
                "feedback_type": feedback_type,
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "cost": cb.total_cost,
                "raw_response": response,
            }
        )

        return flattened_eval
