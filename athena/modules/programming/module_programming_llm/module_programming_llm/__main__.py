import os
from typing import List

import tiktoken
from langchain_core.globals import set_debug, set_verbose

from athena import (
    app,
    submission_selector,
    submissions_consumer,
    feedback_consumer,
    feedback_provider,
)
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from module_programming_llm.approaches import generate_feedback
from module_programming_llm.config import Configuration


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks), submission.id, exercise.id)


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: %s suggestions for submission %d of exercise %d were requested",
                "Graded" if is_graded else "Non-graded", submission.id, exercise.id)
    return await generate_feedback(exercise, submission, is_graded, module_config)



if __name__ == "__main__":
    # Preload for token estimation later
    tiktoken.get_encoding("cl100k_base")
    app.start()

    enable_debug = os.getenv("ENABLE_DEBUGGING_INFO", "False").lower() in ("true", "1")
    if enable_debug:
        set_debug(True)
        set_verbose(True)