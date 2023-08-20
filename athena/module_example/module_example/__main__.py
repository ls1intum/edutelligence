"""
Entry point for the module_example module.
"""
from typing import List
from pydantic import BaseModel, Field
import random

from athena import app, config_schema_provider, submissions_consumer, submission_selector, feedback_consumer, feedback_provider, evaluation_provider, emit_meta
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from athena.storage import store_exercise, store_submissions, store_feedback


@config_schema_provider
class Configuration(BaseModel):
    """Example configuration for the module_example module."""
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

    # Example use of module config
    # If you are not using module_config for your module, you can remove it from the function signature
    logger.info("Config: %s", module_config)
    if module_config.debug:
        emit_meta("costs", "100.00€")
    
    return [
        Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="This is a suggestion.",
            description="There is something wrong here.",
            credits=-1.0,
        )
    ]


@evaluation_provider
def evaluate_feedback(exercise: Exercise, submission: Submission, true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]) -> List[Feedback]:
    logger.info(
        "evaluate_feedback: Evaluation for submission %d of exercise %d was requested with %d true and %d predicted feedbacks", 
        submission.id, exercise.id, len(true_feedbacks), len(predicted_feedbacks)
    )

    # Do something with the true and predicted feedback and return a list of (predicted) feedback with updated meta
    true_feedback_embeddings = [random.random() for _ in true_feedbacks]
    predicted_feedback_embeddings = [random.random() for _ in predicted_feedbacks]

    for feedback, embedding in zip(predicted_feedbacks, predicted_feedback_embeddings):
        # Some example evaluation meta data
        feedback.meta["has_match"] = len([t for t in true_feedback_embeddings if abs(t - embedding) < 0.1]) > 0
        feedback.meta["correctness"] = random.random()

    return predicted_feedbacks


if __name__ == "__main__":
    app.start()
