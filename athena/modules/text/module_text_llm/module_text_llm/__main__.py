import os
from typing import List, Any

import nltk
import tiktoken
from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider, evaluation_provider
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_llm.config import Configuration
from module_text_llm.evaluation import get_feedback_statistics, get_llm_statistics
from module_text_llm.generate_evaluation import generate_evaluation
from module_text_llm.approach_controller import generate_suggestions
from module_text_llm.storage_embeddings import save_embedding
from module_text_llm.generate_embeddings import embed_text
from module_text_llm.index_storage import store_embedding_index
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
    # Saving of the embeddings here.
    submission_id = submission.id
    exercise_id = exercise.id
    embedded_submission = embed_text(submission.text)
    store_embedding_index(exercise_id, submission_id)
    save_embedding(embedded_submission)
    
@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: %s suggestions for submission %d of exercise %d were requested, with approach: %s",
                "Graded" if is_graded else "Non-graded", submission.id, exercise.id, module_config.approach.__class__.__name__)
    return await generate_suggestions(exercise, submission, module_config.approach, module_config.debug)


@evaluation_provider
async def evaluate_feedback(
    exercise: Exercise, submission: Submission, 
    true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback], 
) -> Any:
    logger.info(
        "evaluate_feedback: Evaluation for submission %d of exercise %d was requested with %d true and %d predicted feedbacks",
        submission.id, exercise.id, len(
            true_feedbacks), len(predicted_feedbacks)
    )

    evaluation = {}

    # 1. LLM as a judge
    if len(predicted_feedbacks) > 0 and bool(os.environ.get("LLM_ENABLE_LLM_AS_A_JUDGE")):
        evaluation["llm_as_a_judge"] = await generate_evaluation(exercise, submission, true_feedbacks, predicted_feedbacks)

    # 2. LangSmith runs, token usage, and respose times
    if bool(os.environ.get("LANGCHAIN_TRACING_V2")):
        evaluation["llm_statistics"] = get_llm_statistics(submission)

    # 3. Feedback statistics
    evaluation["feedback_statistics"] = get_feedback_statistics(exercise, true_feedbacks, predicted_feedbacks)

    return evaluation

if __name__ == "__main__":
    nltk.download("punkt_tab")
    tiktoken.get_encoding("cl100k_base")
    app.start()
