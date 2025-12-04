from typing import List

import tiktoken

from athena import (
    app,
    submission_selector,
    submissions_consumer,
    feedback_consumer,
    feedback_provider,
)
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger
from module_programming_quality_llm.config import Configuration

from module_programming_quality_llm.generate_graded_suggestions_by_file import (
    generate_suggestions_by_file as generate_graded_suggestions_by_file,
)
from module_programming_quality_llm.generate_non_graded_suggestions_by_file import (
    generate_suggestions_by_file as generate_non_graded_suggestions_by_file,
)


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)
    logger.warn("@submissions_consumer is not implemented by this module.")


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    logger.warn("@submission_selector is not implemented by this module.")
    return submissions[0]


@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks), submission.id, exercise.id)
    logger.warn("@feedback_consumer is not implemented by this module.")



@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: %s suggestions for submission %d of exercise %d were requested",
                "Graded" if is_graded else "Non-graded", submission.id, exercise.id)
    if is_graded:
        return await generate_graded_suggestions_by_file(exercise, submission, module_config.graded_approach,
                                                         module_config.debug)
    return await generate_non_graded_suggestions_by_file(exercise, submission, module_config.non_graded_approach,
                                                             module_config.debug)



if __name__ == "__main__":
    # Preload for token estimation later
    tiktoken.get_encoding("cl100k_base")
    app.start()