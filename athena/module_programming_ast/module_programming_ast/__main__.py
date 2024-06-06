"""
Entry point for the module_programming_ast module.
"""
import random
from typing import List, Any, cast
from pydantic import BaseModel, Field

from athena import app, config_schema_provider, submissions_consumer, submission_selector, feedback_consumer, feedback_provider, evaluation_provider, emit_meta
from athena.logger import logger
from athena.storage import store_exercise, store_submissions, store_feedback
from athena.programming import Exercise, Submission, Feedback, get_stored_feedback_suggestions, count_stored_submissions
from module_programming_ast.remove_overlapping import filter_overlapping_suggestions
from module_programming_ast.remove_suspicious import filter_suspicious


@config_schema_provider
class Configuration(BaseModel):
    """Example configuration for the module_programming_ast module."""
    debug: bool = Field(False, description="Whether the module is in **debug mode**. This is an example config option.")


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission], module_config: Configuration):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.info("- Submission %d", submission.id)
        zip_content = submission.get_zip()
        # list the files in the zip
        for file in zip_content.namelist():
            logger.info("  - %s", file)
    # Do something with the submissions
    logger.info("Doing stuff")

    # Example use module config
    # If you are not using module_config for your module, you can remove it from the function signature
    logger.info("Config: %s", module_config)
    if module_config.debug:
        emit_meta('debug', True)
        emit_meta('comment', 'You can add any metadata you want here')

    # Add data to exercise
    exercise.meta["some_data"] = "some_value"
    logger.info("- Exercise meta: %s", exercise.meta)

    # Add data to submission
    for submission in submissions:
        submission.meta["some_data"] = "some_value"
        logger.info("- Submission %d meta: %s", submission.id, submission.meta)

    store_exercise(exercise)
    store_submissions(submissions)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.info("- Submission %d", submission.id)
    # Do something with the submissions and return the one that should be assessed next
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received feedbacks for submission %d of exercise %d", submission.id, exercise.id)
    logger.info("process_feedback: Feedbacks: %s", feedbacks)
    # Do something with the feedback
    # Add data to feedback
    for feedback in feedbacks:
        feedback.meta["some_data"] = "some_value"
        store_feedback(feedback)


@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)
    # Do something with the submission and return a list of feedback
    # ThemisML currently only works with Java
    if exercise.programming_language.lower() != "java" or exercise.programming_language.lower() != "python":
        logger.info("The AP-TED module currently only works with Java and Python. Returning no suggestions.")
        return []

    suggested_feedbacks = cast(List[Feedback], list(get_stored_feedback_suggestions(exercise.id, submission.id)))
    logger.debug("Found %d feedback suggestions (unfiltered)", len(suggested_feedbacks))
    suggested_feedbacks = filter_suspicious(suggested_feedbacks, count_stored_submissions(exercise.id))
    logger.debug("Found %d feedback suggestions (removed suspicious suggestions)", len(suggested_feedbacks))
    suggested_feedbacks = filter_overlapping_suggestions(suggested_feedbacks)
    logger.debug("Found %d feedback suggestions (removed overlapping suggestions)", len(suggested_feedbacks))

    logger.info("Suggesting %d filtered feedback suggestions", len(suggested_feedbacks))
    logger.debug("Suggested Feedback suggestions: %s", suggested_feedbacks)

    return suggested_feedbacks



# Only if it makes sense for a module (Optional)
@evaluation_provider
def evaluate_feedback(exercise: Exercise, submission: Submission, true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]) -> Any:
    logger.info(
        "evaluate_feedback: Evaluation for submission %d of exercise %d was requested with %d true and %d predicted feedbacks", 
        submission.id, exercise.id, len(true_feedbacks), len(predicted_feedbacks)
    )

    # Do something with the true and predicted feedback and return the evaluation result
    # Generate some example evaluation result
    evaluation_results = []
    true_feedback_embeddings = [random.random() for _ in true_feedbacks] 
    predicted_feedback_embeddings = [random.random() for _ in predicted_feedbacks]
    for feedback, embedding in zip(predicted_feedbacks, predicted_feedback_embeddings):
        feedback_evaluation = {
            "feedback_id": feedback.id,
            "embedding": embedding,
            "has_match": len([t for t in true_feedback_embeddings if abs(t - embedding) < 0.1]) > 0,
            "correctness": random.random()
        }
        evaluation_results.append(feedback_evaluation)

    return evaluation_results


if __name__ == "__main__":
    app.start()
