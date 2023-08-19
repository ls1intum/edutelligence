from typing import List

import tiktoken

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from module_programming_llm.config import Configuration

from module_programming_llm.generate_suggestions_by_file import generate_suggestions_by_file
from module_programming_llm.split_grading_instructions_by_file import generate_and_store_split_grading_instructions_if_needed
from module_programming_llm.split_problem_statement_by_file import generate_and_store_split_problem_statement_if_needed


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission], module_config: Configuration):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)

    # Split problem statements and grading instructions for later
    generate_and_store_split_problem_statement_if_needed(exercise=exercise, config=module_config.approach, debug=module_config.debug)
    generate_and_store_split_grading_instructions_if_needed(exercise=exercise, config=module_config.approach, debug=module_config.debug)


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
    return await generate_suggestions_by_file(exercise, submission, module_config.approach, module_config.debug)


if __name__ == "__main__":
    tiktoken.get_encoding("cl100k_base")
    app.start()
