from typing import List

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.storage import store_exercise
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger

from module_programming_llm.basic.basic_feedback_provider import suggest_feedback as suggest_feedback_basic
from module_programming_llm.basic.file_instructions import generate_file_grading_instructions, generate_file_problem_statements


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)

    # Split problem statements and grading instructions 
    exercise.meta['file_grading_instructions'] = generate_file_grading_instructions(exercise)
    exercise.meta['file_problem_statements'] = generate_file_problem_statements(exercise)

    store_exercise(exercise)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    # Always return the first submission
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received feedbacks for submission %d of exercise %d.", submission.id, exercise.id)
    logger.info("process_feedback: Feedbacks: %s", feedbacks)
    # Do something with the feedback


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)
    # Do something with the submission and return a list of feedback

    # Check if file based grading instructions and problem statements are available
    if 'file_grading_instructions' in exercise.meta and 'file_problem_statements' in exercise.meta:
        return await suggest_feedback_basic(exercise, submission)
    logger.info("suggest_feedback: No file based grading instructions and problem statements available. Skipping feedback generation.")
    return []


if __name__ == "__main__":
    app.start()
