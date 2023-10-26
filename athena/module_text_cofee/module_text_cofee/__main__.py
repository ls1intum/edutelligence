"""
Entry point for the module_text_cofee module.
"""
from typing import List

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.storage import store_feedback
from athena.text import Exercise, Submission, Feedback, TextLanguageEnum
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
    # CoFee only supports English submissions
    submissions = [s for s in submissions if s.language == TextLanguageEnum.ENGLISH]
    if len(submissions) < 10:
        # CoFee needs at least 10 submissions to work
        logger.info("receive_submissions: Not enough submissions (%d in English), not sending to CoFee", len(submissions))
        return
    adapter.send_submissions(exercise, submissions)


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    for feedback in feedbacks:
        link_feedback_to_block(feedback)
        store_feedback(feedback)


@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info(
        "suggest_feedback: Suggestions for submission %d of exercise %d were requested",
        submission.id, exercise.id
    )
    # TODO: Remove this again
    grading_instruction_to_use = None
    if exercise.grading_criteria:
        if exercise.grading_criteria[0].structured_grading_instructions:
            grading_instruction_to_use = exercise.grading_criteria[0].structured_grading_instructions[0]
    return [
        Feedback(
            id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="Suggestion",
            description="This is referenced test suggestion #1 from CoFee",
            index_start=10,
            index_end=20,
            credits=1.0,
            structured_grading_instruction_id=grading_instruction_to_use.id if grading_instruction_to_use else None,
            meta={}
        ),
        Feedback(
            id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="Suggestion",
            description="This is referenced test suggestion #2 from CoFee",
            index_start=30,
            index_end=40,
            credits=-1.0,
            structured_grading_instruction_id=None,
            meta={}
        ),
        Feedback(
            id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            title="Suggestion",
            description="This is an unreferenced suggestion from CoFee",
            index_start=None,
            index_end=None,
            credits=2.0,
            structured_grading_instruction_id=None,
            meta={}
        )
    ]
    suggestions = suggest_feedback_for_submission(submission)
    logger.info("suggest_feedback: Returning %d suggestions", len(suggestions))
    return suggestions


if __name__ == "__main__":
    app.start()
