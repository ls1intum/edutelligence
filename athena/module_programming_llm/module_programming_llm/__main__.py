import os
from typing import List

import tiktoken
from langchain.globals import set_debug, set_verbose

from athena import (
    app,
    submission_selector,
    submissions_consumer,
    feedback_consumer,
    feedback_provider,
)
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from module_programming_llm.config import Configuration

from module_programming_llm.graded.basic_by_file.generate import generate_graded_basic_by_file_suggestions
from module_programming_llm.graded.zero_shot.generate import generate_graded_zero_shot_suggestions
from module_programming_llm.guided.basic_by_file.generate import generate_guided_basic_by_file_suggestions
from module_programming_llm.guided.zero_shot.generate import generate_guided_zero_shot_suggestions


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks),
                submission.id, exercise.id)


@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> \
List[Feedback]:
    logger.info("suggest_feedback: %s suggestions for submission %d of exercise %d were requested",
                "Graded" if is_graded else "Non-graded", submission.id, exercise.id)
    if is_graded:
        if module_config.graded_basic_by_file:
            return await generate_graded_basic_by_file_suggestions(exercise, submission,
                                                                   module_config.graded_basic_by_file,
                                                                   module_config.debug)
        elif module_config.graded_zero_shot:
            return await generate_graded_zero_shot_suggestions(exercise, submission,
                                                               module_config.graded_zero_shot,
                                                               module_config.debug)
    else:
        if module_config.guided_basic_by_file:
            return await generate_guided_basic_by_file_suggestions(exercise, submission,
                                                                   module_config.guided_basic_by_file,
                                                                   module_config.debug)
        elif module_config.guided_zero_shot:
            return await generate_guided_zero_shot_suggestions(exercise, submission, module_config.guided_zero_shot,
                                                               module_config.debug)

    return []


if __name__ == "__main__":
    # Preload for token estimation later
    tiktoken.get_encoding("cl100k_base")
    app.start()

    enable_debug = os.environ.get("ENABLE_DEBUGGING_INFO", False)
    if enable_debug:
        set_debug(True)
        set_verbose(True)
