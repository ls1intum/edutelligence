"""
Entry point for the module_programming_apted module.
"""
import random
from typing import List, Any, cast
from pydantic import BaseModel, Field
from module_programming_apted.convert_code_to_ast.get_feedback_methods import get_feedback_method
from module_programming_apted.feedback_suggestions.feedback_suggestions import create_feedback_suggestions
from athena import (app, config_schema_provider, submissions_consumer, submission_selector, feedback_consumer,
                    feedback_provider, evaluation_provider, emit_meta)
from athena.logger import logger
from athena.storage import store_exercise, store_submissions, store_feedback, store_feedback_suggestions
from athena.programming import (Exercise, Submission, Feedback, get_stored_feedback_suggestions,
                                count_stored_submissions, get_stored_submissions)
from module_programming_apted.remove_overlapping import filter_overlapping_suggestions
from module_programming_apted.remove_suspicious import filter_suspicious


@config_schema_provider
class Configuration(BaseModel):
    """Example configuration for the module_programming_apted module."""
    debug: bool = Field(False, description="Whether the module is in **debug mode**. This is an example config option.")


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission], module_config: Configuration):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.info("- Submission %d", submission.id)
        repo = submission.get_repository()
        # list the files in the repository
        for file in repo.git.ls_files().splitlines():
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
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d", len(feedbacks),
                submission.id, exercise.id)
    logger.info("process_feedback: Feedbacks: %s", feedbacks)

    programming_language = exercise.programming_language.lower()
    # Currently only works with Java and Python - can be extended with more languages if the grammar is available
    if programming_language not in ["java", "python"]:
        logger.info("AP-TED currently only works with Java and Python. Not consuming feedback.")
        return

    # Remove unreferenced feedbacks
    feedbacks = list(filter(lambda f: f.file_path is not None and f.line_start is not None, feedbacks))

    # Add method metadata to feedbacks
    feedbacks_with_method = []
    for feedback in feedbacks:
        feedback_method = get_feedback_method(submission, feedback, programming_language)
        if feedback_method is None:
            # don't consider feedback without a method
            continue
        logger.debug("Feedback #%d: Found method %s", feedback.id, feedback_method.name)
        feedback.meta["method_name"] = feedback_method.name
        feedback.meta["method_code"] = feedback_method.source_code
        feedback.meta["method_line_start"] = feedback_method.line_start
        feedback.meta["method_line_end"] = feedback_method.line_end
        feedback.meta["method_ast"] = feedback_method.ast
        feedbacks_with_method.append(feedback)
    feedbacks = feedbacks_with_method

    # find all submissions for this exercise
    exercise_submissions = cast(List[Submission], list(get_stored_submissions(exercise.id)))

    # create feedback suggestions
    logger.info("Creating feedback suggestions for %d feedbacks", len(feedbacks))
    feedback_suggestions = create_feedback_suggestions(exercise_submissions, feedbacks, programming_language)

    # additionally, store metadata about how impactful each feedback was, i.e. how many suggestions were given based on it
    for feedback in feedbacks:
        # count how many suggestions were given based on this feedback
        feedback.meta["n_feedback_suggestions"] = len(
            [f for f in feedback_suggestions if f.meta["original_feedback_id"] == feedback.id])
        # store the information on the suggestions as well for quicker access later
        for suggestion in feedback_suggestions:
            if suggestion.meta["original_feedback_id"] == feedback.id:
                suggestion.meta["n_feedback_suggestions"] = feedback.meta["n_feedback_suggestions"]

    # save to database
    # type: ignore
    store_feedback_suggestions(feedback_suggestions)
    for feedback in feedbacks:
        store_feedback(feedback)

    logger.debug("Feedbacks processed")


@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id,
                exercise.id)
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
def evaluate_feedback(exercise: Exercise, submission: Submission, true_feedbacks: List[Feedback],
                      predicted_feedbacks: List[Feedback]) -> Any:
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
