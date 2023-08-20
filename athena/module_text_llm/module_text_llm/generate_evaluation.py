from typing import List, Sequence
from pydantic import BaseModel, Field
import json

from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_llm.helpers.models import evaluation_model
from module_text_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions, 
    check_prompt_length_and_omit_features_if_necessary, 
    predict_and_parse
)
from module_text_llm.helpers.utils import add_sentence_numbers, get_line_range_from_index_range
from module_text_llm.prompts.generate_evaluation import system_message, human_message

class CorrectnessMetric(BaseModel):
    """Correctness metric for a single feedback"""
    id: int = Field(..., description="Feedback ID")
    reason: str = Field(..., description="Step-by-step reasoning")
    score: float = Field(..., description="Correctness score from 0.0 to 1.0")


class Evaluation(BaseModel):
    """Collection of feedback metrics making up an evaluation"""
    metrics: Sequence[CorrectnessMetric] = Field(...)


async def generate_evaluation(exercise: Exercise, submission: Submission, true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]) -> List[Feedback]:
    if evaluation_model is None:
        raise EnvironmentError("No evaluation model available, please set up LLM_EVALUATION_MODEL correctly.")
    max_input_tokens = 3000

    def feedback_to_dict(feedback: Feedback):
        line_start, line_end = get_line_range_from_index_range(feedback.index_start, feedback.index_end, submission.text)
        return {
            "id": feedback.id,
            "title": feedback.title,
            "description": feedback.description,
            "line_start": line_start,
            "line_end": line_end,
            "credits": feedback.credits
        }

    prompt_input = {
        "submission": add_sentence_numbers(submission.text),
        "true_feedbacks": json.dumps([feedback_to_dict(feedback) for feedback in true_feedbacks]),
        "predicted_feedbacks": json.dumps([feedback_to_dict(feedback) for feedback in predicted_feedbacks]),
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=evaluation_model, 
        system_message=system_message, 
        human_message=human_message, 
        pydantic_object=Evaluation
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = ["submission"]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input= prompt_input,
        max_input_tokens=max_input_tokens,
        omittable_features=omittable_features,
        debug=False
    )

    if not should_run:
        logger.warning("Evaluation input too long. Skipping.")
        return predicted_feedbacks
    
    result = await predict_and_parse(
        model=evaluation_model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=Evaluation
    )

    if result is None:
        logger.warning("Evaluation failed. Skipping.")
        return predicted_feedbacks
    
    # Add result to feedbacks
    for feedback in predicted_feedbacks:
        metric = next((metric for metric in result.metrics if metric.id == feedback.id), None)
        if metric is None:
            logger.warning("Feedback %s not found in evaluation result. Skipping.", feedback.id)
            continue

        feedback.meta["correctness"] = {
            "score": metric.score,
            "reason": metric.reason,
        }

    return predicted_feedbacks