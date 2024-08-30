from typing import List, Optional
from langchain_community.callbacks import get_openai_callback
from langchain.chat_models import AzureChatOpenAI
from langchain_core.messages import BaseMessage
from langchain.output_parsers import PydanticOutputParser
from pydantic.error_wrappers import ValidationError

from module_text_llm.text_evaluation.evaluation_schemas import Evaluation, MetricEvaluations


def get_logprobs_langchain(prompt: List[BaseMessage], model: AzureChatOpenAI) -> Optional[Evaluation]:
    # Invoke the model with the formatted prompt
    with get_openai_callback() as cb:
        response = model.invoke(prompt, max_tokens=100, logprobs=True, top_logprobs=5, temperature=0)

        total_tokens = cb.total_tokens
        prompt_tokens = cb.prompt_tokens
        completion_tokens = cb.completion_tokens
        cost = cb.total_cost

        output_parser = PydanticOutputParser(pydantic_object=MetricEvaluations)

        try:
            parsed_response = output_parser.parse(response.content)
        except ValidationError as e:
            print(f"Response validation failed: {e}")
            # In the future, we should probably have some recovery mechanism here (i.e. fix the output with another prompt)
            return None

        return Evaluation(
            response=response,
            parsed_response=parsed_response,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
        )
