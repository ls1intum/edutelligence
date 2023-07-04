"""
Entry point for the module_programming_themisml module.
"""
from typing import List, cast

from athena import app, submissions_consumer, submission_selector, feedback_consumer, feedback_provider
from athena.database import get_db
from athena.models import DBProgrammingFeedback
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from athena.storage import store_feedback

from .extract_methods import extract_methods
from .feedback_suggestions import get_feedback_suggestions


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d submissions for exercise %d", len(submissions), exercise.id)
    for submission in submissions:
        logger.info("- Submission %d", submission.id)
    # It might be possible to cleverly find "good" submissions here later
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedback: Feedback):
    logger.info("process_feedback: Received feedback for submission %d of exercise %d", submission.id, exercise.id)
    logger.info("process_feedback: Feedback: %s", feedback)

    if feedback.file_path is None or feedback.line_start is None:
        logger.debug("Cannot process without knowledge about method.")
        return

    # find method that the feedback is on
    code = submission.get_code(feedback.file_path)
    methods = extract_methods(code)
    feedback_method = None
    for m in methods:
        # method has to contain all feedback lines
        if m.line_start <= feedback.line_start and m.line_end >= feedback.line_end:
            feedback_method = m
            break

    feedback.meta["method_name"] = feedback_method.name if feedback_method else None
    store_feedback(feedback)


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)

    # find all methods in all files
    method_blocks = {}
    repo_zip = submission.get_zip()
    for file_path in repo_zip.namelist():
        with repo_zip.open(file_path, "r") as f:
            try:
                file_content = f.read().decode("utf-8")
            except UnicodeDecodeError:
                # skip binary files
                continue
        method_blocks[file_path] = extract_methods(file_content)

    with get_db() as db:
        # find all feedbacks for this exercise, except for the current submission
        exercise_feedbacks = db.query(DBProgrammingFeedback) \
            .filter_by(exercise_id=exercise.id) \
            .filter(DBProgrammingFeedback.submission_id != submission.id) \
            .all()
        suggested_feedbacks = await get_feedback_suggestions(method_blocks, exercise_feedbacks, include_code=False)

    return suggested_feedbacks


if __name__ == "__main__":
    app.start()
