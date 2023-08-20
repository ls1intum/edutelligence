from typing import Dict, List

import nltk
import tiktoken

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider, evaluation_provider
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_llm.config import Configuration
from module_text_llm.generate_suggestions import generate_suggestions
from module_text_llm.generate_evaluation import generate_evaluation


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
async def suggest_feedback(exercise: Exercise, submission: Submission, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id, exercise.id)
    return await generate_suggestions(exercise, submission, module_config.approach, module_config.debug)


@evaluation_provider
async def evaluate_feedback(
        exercise: Exercise, submission: Submission, 
        true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback], 
        module_config: Configuration
    ) -> Dict[int, dict]:
    logger.info(
        "evaluate_feedback: Evaluation for submission %d of exercise %d was requested with %d true and %d predicted feedbacks", 
        submission.id, exercise.id, len(true_feedbacks), len(predicted_feedbacks)
    )
    return await generate_evaluation(exercise, submission, true_feedbacks, predicted_feedbacks, debug=module_config.debug)


if __name__ == "__main__":
    nltk.download("punkt")
    tiktoken.get_encoding("cl100k_base")
    app.start()