"""
Entry point for the module_text_cofee module.
"""
from typing import List

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.storage import store_feedback
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_cofee import adapter
from module_text_cofee.information_gain import calculate_information_gain # type: ignore
from module_text_cofee.link_feedback_to_block import link_feedback_to_block
from module_text_cofee.suggest_feedback import suggest_feedback_for_submission


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.debug("- Submission %d", submission.id)
    return max(
        submissions,
        key=lambda submission: calculate_information_gain(submission, [s.id for s in submissions])
    )


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)
    if len(submissions) < 10:
        # CoFee needs at least 10 submissions to work
        logger.info("receive_submissions: Not enough submissions, not sending to CoFee")
        return
    adapter.send_submissions(exercise, submissions)


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedback: Feedback):
    link_feedback_to_block(feedback)
    store_feedback(feedback)


@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info(
        "suggest_feedback: Suggestions for submission %d of exercise %d were requested",
        submission.id, exercise.id
    )
    return suggest_feedback_for_submission(submission)


if __name__ == "__main__":
    app.start()
