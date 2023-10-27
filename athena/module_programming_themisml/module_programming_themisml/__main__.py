"""
Entry point for the module_programming_themisml module.
"""
from typing import List, cast

from athena import app, submissions_consumer, submission_selector, feedback_consumer, feedback_provider
from athena.programming import Exercise, Submission, Feedback, get_stored_feedback_suggestions, get_stored_submissions, count_stored_submissions
from athena.logger import logger
from athena.storage import store_feedback
from athena.storage.feedback_storage import store_feedback_suggestions

from .extract_methods import get_feedback_method
from .feedback_suggestions import create_feedback_suggestions, filter_overlapping_suggestions, filter_suspicious


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)
    # Nothing else to do


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.info("- Submission %d", submission.id)
    # It might be possible to cleverly find "good" submissions here later
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d", len(feedbacks), submission.id, exercise.id)
    logger.info("process_feedback: Feedbacks: %s", feedbacks)

    # ThemisML currently only works with Java
    if exercise.programming_language.lower() != "java":
        logger.info("ThemisML only works with Java. Not consuming feedback.")
        return

    # Remove unreferenced feedbacks
    feedbacks = list(filter(lambda f: f.file_path is not None and f.line_start is not None, feedbacks))

    # Add method metadata to feedbacks
    feedbacks_with_method = []
    for feedback in feedbacks:
        feedback_method = get_feedback_method(submission, feedback)
        if feedback_method is None:
            # don't consider feedback without a method
            continue
        logger.debug("Feedback #%d: Found method %s", feedback.id, feedback_method.name)
        feedback.meta["method_name"] = feedback_method.name
        feedback.meta["method_code"] = feedback_method.source_code
        feedback.meta["method_line_start"] = feedback_method.line_start
        feedback.meta["method_line_end"] = feedback_method.line_end
        feedbacks_with_method.append(feedback)
    feedbacks = feedbacks_with_method

    # find all submissions for this exercise
    exercise_submissions = cast(List[Submission], list(get_stored_submissions(exercise.id)))

    # create feedback suggestions
    logger.info("Creating feedback suggestions for %d feedbacks", len(feedbacks))
    feedback_suggestions = create_feedback_suggestions(exercise_submissions, feedbacks)

    # additionally, store metadata about how impactful each feedback was, i.e. how many suggestions were given based on it
    for feedback in feedbacks:
        # count how many suggestions were given based on this feedback
        feedback.meta["n_feedback_suggestions"] = len([f for f in feedback_suggestions if f.meta["original_feedback_id"] == feedback.id])
        # store the information on the suggestions as well for quicker access later
        for suggestion in feedback_suggestions:
            if suggestion.meta["original_feedback_id"] == feedback.id:
                suggestion.meta["n_feedback_suggestions"] = feedback.meta["n_feedback_suggestions"]

    # save to database
    store_feedback_suggestions(feedback_suggestions)  # type: ignore
    for feedback in feedbacks:
        store_feedback(feedback)

    logger.debug("Feedbacks processed")


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)

    # ThemisML currently only works with Java
    if exercise.programming_language.lower() != "java":
        logger.info("ThemisML only works with Java. Returning no suggestions.")
        return []
    
    # TODO: Remove this again
    grading_instruction_to_use = None
    if exercise.grading_criteria:
        if exercise.grading_criteria[0].structured_grading_instructions:
            grading_instruction_to_use = exercise.grading_criteria[0].structured_grading_instructions[0]
    return [
        Feedback(
            id=None,
            title="Feedback Suggestion",
            description="This is referenced test suggestion #1 from ThemisML",
            credits=-1,
            structured_grading_instruction_id=grading_instruction_to_use.id if grading_instruction_to_use else None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            file_path="src/de/athena/BubbleSort.java",
            line_start=14,
            line_end=14,
            meta={},
        ),
        Feedback(
            id=None,
            title="Feedback Suggestion",
            description="This is referenced test suggestion #1 from ThemisML",
            credits=1,
            structured_grading_instruction_id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            file_path="src/de/athena/Client.java",
            line_start=18,
            line_end=18,
            meta={},
        ),
        Feedback(
            id=None,
            title="Feedback Suggestion",
            description="This is an unreferenced test suggestion from ThemisML",
            credits=-2,
            structured_grading_instruction_id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            file_path=None,
            line_start=None,
            line_end=None,
            meta={},
        )
    ]

    suggested_feedbacks = cast(List[Feedback], list(get_stored_feedback_suggestions(exercise.id, submission.id)))
    logger.debug("Found %d feedback suggestions (unfiltered)", len(suggested_feedbacks))
    suggested_feedbacks = filter_suspicious(suggested_feedbacks, count_stored_submissions(exercise.id))
    logger.debug("Found %d feedback suggestions (removed suspicious suggestions)", len(suggested_feedbacks))
    suggested_feedbacks = filter_overlapping_suggestions(suggested_feedbacks)
    logger.debug("Found %d feedback suggestions (removed overlapping suggestions)", len(suggested_feedbacks))

    logger.info("Suggesting %d filtered feedback suggestions", len(suggested_feedbacks))
    logger.debug("Suggested Feedback suggestions: %s", suggested_feedbacks)

    return suggested_feedbacks


if __name__ == "__main__":
    app.start()
