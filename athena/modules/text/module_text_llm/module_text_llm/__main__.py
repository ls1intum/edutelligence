import os
from typing import List, Any

import nltk
import tiktoken
from athena import app, submission_selector, submissions_consumer,generate_statistics, feedback_consumer, feedback_provider, evaluation_provider,feedback_storer

from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from module_text_llm.config import Configuration
from module_text_llm.evaluation import get_feedback_statistics, get_llm_statistics
from module_text_llm.generate_evaluation import generate_evaluation
from module_text_llm.approach_controller import generate_suggestions
from module_text_llm.helpers.detect_suspicios_submission import hybrid_suspicion_score, llm_check
from module_text_llm.helpers.feedback_icl.store_feedback_icl import store_feedback_icl
from module_text_llm.few_shot_chain_of_thought_approach import FewShotChainOfThoughtConfig
#Test Demo
from module_text_llm.analytics.compile import compile

@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    logger.info("receive_submissions: Received %d submissions for exercise %d", len(submissions), exercise.id)


@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    logger.info("select_submission: Received %d, submissions for exercise %d", len(submissions), exercise.id)
    return submissions[0]


@feedback_storer # used for playground
def do_thing(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks), submission.id, exercise.id)
    store_feedback_icl(submission, exercise, feedbacks)
    logger.info("Embedding saved for submission %d of exercise %d.", submission.id, exercise.id)
    
@feedback_consumer # used for Artemis
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    logger.info("process_feedback: Received %d feedbacks for submission %d of exercise %d.", len(feedbacks), submission.id, exercise.id)
    store_feedback_icl(submission, exercise, feedbacks)
    logger.info("Embedding saved for submission %d of exercise %d.", submission.id, exercise.id)
    

@generate_statistics
async def compile_analytics(results: dict):
    logger.info("generate_statistics: Generating statistics")
    return compile(results)

@feedback_provider
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: %s suggestions for submission %d of exercise %d were requested, with approach: %s",
                "Graded" if is_graded else "Non-graded", submission.id, exercise.id, module_config.approach.__class__.__name__)

    if not is_graded:    
        is_sus, score = hybrid_suspicion_score(submission.text, threshold=0.8)
        if is_sus:
            logger.info("Suspicious submission detected with score %f", score)
            is_suspicious,suspicios_text = await llm_check(submission.text)
            if is_suspicious:
                logger.info("Suspicious submission detected by LLM with text %s", suspicios_text)
                return [Feedback(title="Instructors need to review this submission", description="This Submission potentially violates the content policy!", credits=-1.0, exercise_id=exercise.id, submission_id=submission.id, is_graded=is_graded)]
        module_config.approach = FewShotChainOfThoughtConfig()
        return await generate_suggestions(exercise, submission, module_config.approach, module_config.debug, is_graded)
    return await generate_suggestions(exercise, submission, module_config.approach, module_config.debug, is_graded)


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
