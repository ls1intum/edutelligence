from typing import List

import nltk

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from .suggest_feedback_basic import suggest_feedback_basic


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedback: Feedback):
    logger.info("process_feedback: Received feedback for submission %d of exercise %d.", submission.id, exercise.id)


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)
    return await suggest_feedback_basic(exercise, submission)


if __name__ == "__main__":
    nltk.download("punkt")
    app.start()