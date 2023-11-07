import json
import os
from typing import List, Any

import nltk
import tiktoken
from langsmith import Client as LangsmithClient
from langsmith.schemas import Run

from athena import app, get_experiment_environment, submission_selector, submissions_consumer, feedback_consumer, feedback_provider, evaluation_provider
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_llm.config import Configuration
from module_text_llm.generate_suggestions import generate_suggestions
from module_text_llm.generate_evaluation import generate_evaluation


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks), submission.id, exercise.id)


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)
    return await generate_suggestions(exercise, submission, module_config.approach, module_config.debug)


@evaluation_provider
async def evaluate_feedback(
    exercise: Exercise, submission: Submission, 
    true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback], 
) -> Any:
    logger.info(
        "evaluate_feedback: Evaluation for submission %d of exercise %d was requested with %d true and %d predicted feedbacks", 
        submission.id, exercise.id, len(true_feedbacks), len(predicted_feedbacks)
    )
    
    evaluation = {}
    if bool(os.environ.get("LLM_ENABLE_LLM_AS_A_JUDGE")):
        evaluation["llm_as_a_judge"] = await generate_evaluation(exercise, submission, true_feedbacks, predicted_feedbacks)

    # Gather LLM token usage and response times
    if bool(os.environ.get("LANGCHAIN_TRACING_V2")):
        experiment = get_experiment_environment()
        client = LangsmithClient()
        project_name = os.environ.get("LANGCHAIN_PROJECT")
        runs = list(client.list_runs(
            project_name=project_name,
            filter=f'and(has(tags, "run-{experiment.run_id}"), has(tags, "submission-{submission.id}"))'
        ))
        logger.info("evaluate_feedback: Found %d runs for submission %d of exercise %d.", len(runs), submission.id, exercise.id)
        
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

        if suggestion_runs or evaluation_runs:
            evaluation["runs"] = {}
            if suggestion_runs:
                evaluation["runs"]["suggestions"] = {
                    "count": len(suggestion_runs),
                    **get_statistics(suggestion_runs),
                    "runs": [json.loads(run.json()) for run in suggestion_runs]
                }
            if evaluation_runs:
                evaluation["runs"]["evaluation"] = {
                    "count": len(evaluation_runs),
                    **get_statistics(evaluation_runs),
                    "runs": [json.loads(run.json()) for run in evaluation_runs]
                }

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
        if feedback.structured_grading_instruction_id:
            actual_feedback_with_grading_instructions.append(feedback)
            actual_sgi_usage[feedback.structured_grading_instruction_id] += 1

    # Count SGIs in suggested feedbacks
    for feedback in predicted_feedbacks:
        if feedback.structured_grading_instruction_id:
            suggestions_with_grading_instructions.append(feedback)
            suggested_sgi_usage[feedback.structured_grading_instruction_id] += 1

    actual_feedback_with_grading_instructions_count = len(actual_feedback_with_grading_instructions)
    suggestions_with_grading_instructions_count = len(suggestions_with_grading_instructions)

    # Match SGIs
    matched_feedback = 0
    unmatched_feedback = actual_feedback_count - actual_feedback_with_grading_instructions_count
    unmatched_suggestions = suggestions_count - suggestions_with_grading_instructions_count
    
    for feedback in actual_feedback_with_grading_instructions:
        for index, suggestion in enumerate(suggestions_with_grading_instructions):
            if feedback.structured_grading_instruction_id == suggestion.structured_grading_instruction_id:
                matched_feedback += 1
                del suggestions_with_grading_instructions[index]
                break
        else:
            unmatched_feedback += 1

    unmatched_suggestions += len(suggestions_with_grading_instructions)

    evaluation["feedback_statistics"] = {
        "actual_feedback_count": actual_feedback_count,
        "suggestions_count": suggestions_count,
        "actual_feedback_with_grading_instructions_count": actual_feedback_with_grading_instructions_count,
        "suggestions_with_grading_instructions_count": suggestions_with_grading_instructions_count,
        "actual_sgi_usage": actual_sgi_usage,
        "suggested_sgi_usage": suggested_sgi_usage,
        "matched_feedback": matched_feedback,
        "unmatched_feedback": unmatched_feedback,
        "unmatched_suggestions": unmatched_suggestions,
    }
    
    return evaluation

if __name__ == "__main__":
    nltk.download("punkt")
    tiktoken.get_encoding("cl100k_base")
    app.start()