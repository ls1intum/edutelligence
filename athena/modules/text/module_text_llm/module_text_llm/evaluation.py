import json
import os
from typing import List

from langsmith import Client as LangSmithClient
from langsmith.schemas import Run

from athena import get_experiment_environment
from athena.text import Exercise, Submission, Feedback


def get_llm_statistics(submission: Submission):
    experiment = get_experiment_environment()
    client = LangSmithClient()
    project_name = os.environ.get("LANGCHAIN_PROJECT")
    runs = list(client.list_runs(
        project_name=project_name,
        filter=f'has(tags, "submission-{submission.id}")' if experiment.run_id is None else f'and(has(tags, "run-{experiment.run_id}"), has(tags, "submission-{submission.id}"))'
    ))

    def get_statistics(runs: List[Run]):
        return {
            "response_time": sum((run.end_time - run.start_time).total_seconds() for run in runs if run.end_time is not None),
            "prompt_tokens": sum(run.prompt_tokens for run in runs if run.prompt_tokens is not None),
            "completion_tokens": sum(run.completion_tokens for run in runs if run.completion_tokens is not None),
            "total_tokens": sum(run.total_tokens for run in runs if run.total_tokens is not None),
        }

    suggestion_runs = []
    evaluation_runs = []
    for run in runs:
        if "evaluation" in (run.tags or []):
            evaluation_runs.append(run)
        else:
            suggestion_runs.append(run)

    llm_statistics = {}
    if suggestion_runs or evaluation_runs:
        if suggestion_runs:
            llm_statistics["suggestions"] = {
                "count": len(suggestion_runs),
                **get_statistics(suggestion_runs),
                "runs": [json.loads(run.model_dump_json()) for run in suggestion_runs]
            }
        if evaluation_runs:
            llm_statistics["evaluation"] = {
                "count": len(evaluation_runs),
                **get_statistics(evaluation_runs),
                "runs": [json.loads(run.model_dump_json()) for run in evaluation_runs]
            }

    return llm_statistics


def get_feedback_statistics(exercise: Exercise, true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]):
    actual_feedback_count = len(true_feedbacks)
    actual_feedback_with_grading_instructions = []
    suggestions_count = len(predicted_feedbacks)
    suggestions_with_grading_instructions = []

    # Init usage counts for SGIs
    actual_sgi_usage = {
        sgi.id: 0 for criterion in exercise.grading_criteria or [] for sgi in criterion.structured_grading_instructions
    }
    suggested_sgi_usage = {
        sgi.id: 0 for criterion in exercise.grading_criteria or [] for sgi in criterion.structured_grading_instructions
    }

    # Count SGIs in actual feedbacks
    for feedback in true_feedbacks:
        if feedback.structured_grading_instruction_id and feedback.structured_grading_instruction_id in actual_sgi_usage:
            actual_feedback_with_grading_instructions.append(feedback)
            actual_sgi_usage[feedback.structured_grading_instruction_id] += 1

    # Count SGIs in suggested feedbacks
    for feedback in predicted_feedbacks:
        if feedback.structured_grading_instruction_id and feedback.structured_grading_instruction_id in suggested_sgi_usage:
            suggestions_with_grading_instructions.append(feedback)
            suggested_sgi_usage[feedback.structured_grading_instruction_id] += 1

    unmatched_suggestions_with_grading_instructions = suggestions_with_grading_instructions.copy()

    # Match SGIs
    matched_feedback = 0
    unmatched_feedback = actual_feedback_count - len(actual_feedback_with_grading_instructions)
    unmatched_suggestions = suggestions_count - len(suggestions_with_grading_instructions)

    for feedback in actual_feedback_with_grading_instructions:
        for index, suggestion in enumerate(unmatched_suggestions_with_grading_instructions):
            if feedback.structured_grading_instruction_id == suggestion.structured_grading_instruction_id:
                matched_feedback += 1
                del unmatched_suggestions_with_grading_instructions[index]
                break
        else:
            unmatched_feedback += 1

    unmatched_suggestions += len(unmatched_suggestions_with_grading_instructions)

    feedback_statistics = {
        "actual_feedback_count": actual_feedback_count,
        "suggestions_count": suggestions_count,
        "actual_feedback_with_grading_instructions_count": len(actual_feedback_with_grading_instructions),
        "suggestions_with_grading_instructions_count":len(suggestions_with_grading_instructions),
        "actual_sgi_usage": actual_sgi_usage,
        "suggested_sgi_usage": suggested_sgi_usage,
        "matched_feedback": matched_feedback,
        "unmatched_feedback": unmatched_feedback,
        "unmatched_suggestions": unmatched_suggestions,
    }

    return feedback_statistics
