import json
import os
from typing import List, Optional

from langchain_community.callbacks import get_openai_callback
from langchain_openai.chat_models import AzureChatOpenAI
from pandas import DataFrame
from tqdm import tqdm

from model.evaluation_model import Metric, MetricEvaluationRequest, MetricEvaluations
from prompts.llm_evaluation_prompt import get_formatted_prompt
from service.json_service import group_exercise_data


def generate_evaluation_requests(
    data: DataFrame, metrics: List[Metric], feedback_type_filter: Optional[str] = None
) -> List[MetricEvaluationRequest]:
    """Generates evaluation requests for the LLM judge based on the provided data and metrics."""
    requests: List[MetricEvaluationRequest] = []

    exercises = group_exercise_data(data, feedback_type_filter=feedback_type_filter)

    for exercise in exercises:
        for submission in exercise.submissions:
            if submission.feedbacks is None:
                prompt = get_formatted_prompt(exercise, submission, [], metrics)
                requests.append(
                    MetricEvaluationRequest(
                        prompt=prompt,
                        exercise_id=exercise.id,
                        submission_id=submission.id,
                        feedback_type="default",
                        metrics=metrics,
                    )
                )
            elif isinstance(submission.feedbacks, list):
                prompt = get_formatted_prompt(
                    exercise, submission, submission.feedbacks, metrics
                )
                requests.append(
                    MetricEvaluationRequest(
                        prompt=prompt,
                        exercise_id=exercise.id,
                        submission_id=submission.id,
                        feedback_type="default",
                        metrics=metrics,
                    )
                )
            elif isinstance(submission.feedbacks, dict):
                for feedback_type, feedback in submission.feedbacks.items():
                    prompt = get_formatted_prompt(
                        exercise, submission, feedback, metrics
                    )
                    requests.append(
                        MetricEvaluationRequest(
                            prompt=prompt,
                            exercise_id=exercise.id,
                            submission_id=submission.id,
                            feedback_type=feedback_type,
                            metrics=metrics,
                        )
                    )

    return requests


def process_feedback_evaluations(
    requests: List[MetricEvaluationRequest],
    output_path: str,
    model: AzureChatOpenAI,
    metrics: List[Metric],
) -> None:
    """Processes feedback evaluations using the LLM as a judge and saves the results."""
    selected_values = {}
    total_cost = 0.0

    evaluation_progress = {
        "current_submission_index": None,
        "current_exercise_index": None,
        "selected_values": selected_values,
        "has_started_evaluating": False,
        "is_finished_evaluating": True,
    }

    progress_bar = tqdm(requests, desc="Processing")

    for request in progress_bar:
        evaluation_progress["has_started_evaluating"] = True
        with get_openai_callback() as cb:
            metric_evaluations = model.with_structured_output(MetricEvaluations).invoke(
                request.prompt, max_tokens=100, temperature=0
            )
        total_cost += cb.total_cost
        progress_bar.set_postfix({"Current Cost Estimate (USD)": f"{total_cost:.6f}"})

        if isinstance(metric_evaluations, MetricEvaluations):
            evaluated_metric_titles = {
                evaluation.title for evaluation in metric_evaluations.evaluations
            }
            expected_metric_titles = {metric.title for metric in metrics}
            if evaluated_metric_titles != expected_metric_titles:
                print(
                    f"Evaluated metrics do not match expected metrics. Expected: {expected_metric_titles}, Got: {evaluated_metric_titles}, Given: {request}"
                )
                evaluation_progress["is_finished_evaluating"] = False
                continue
        else:
            print(
                f"The LLM returned an unexpected format given this request: {request}"
            )
            evaluation_progress["is_finished_evaluating"] = False
            continue

        if request.exercise_id not in selected_values:
            selected_values[request.exercise_id] = {}
        if request.submission_id not in selected_values[request.exercise_id]:
            selected_values[request.exercise_id][request.submission_id] = {}
        if (
            request.feedback_type
            not in selected_values[request.exercise_id][request.submission_id]
        ):
            selected_values[request.exercise_id][request.submission_id][
                request.feedback_type
            ] = {}

        for metric_evaluation in metric_evaluations.evaluations:
            selected_values[request.exercise_id][request.submission_id][
                request.feedback_type
            ][metric_evaluation.title] = metric_evaluation.score

        selected_values[request.exercise_id][request.submission_id][
            request.feedback_type
        ]["meta"] = {
            "total_tokens": cb.total_tokens,
            "prompt_tokens": cb.prompt_tokens,
            "completion_tokens": cb.completion_tokens,
            "cost": cb.total_cost,
        }

    os.makedirs(output_path, exist_ok=True)
    file_path = os.path.join(output_path, "evaluation_progress_llm-as-a-judge.json")
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(evaluation_progress, file, indent=4)

    print("\nSummary of Evaluation:")
    print(f"Total evaluated exercises: {len(selected_values)}")
    print(f"Total evaluated submissions: {len([sub for ex in selected_values.values() for sub in ex.values()])}")
    print(f"Total evaluated feedbacks: {len([fb for ex in selected_values.values() for sub in ex.values() for fb in sub.values()])}")
    print(f"Total cost: ${total_cost:.6f} USD")
