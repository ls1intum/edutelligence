from typing import List

import nltk
import tiktoken

from athena import app, submission_selector, submissions_consumer, feedback_consumer, feedback_provider
from athena.logger import logger
from athena.modeling import Exercise, Feedback, Submission
from module_modeling_llm.config import Configuration
from module_modeling_llm.core.filter_feedback import filter_feedback
from module_modeling_llm.core.generate_suggestions import generate_suggestions
from module_modeling_llm.core.get_structured_grading_instructions import get_structured_grading_instructions
from module_modeling_llm.utils.convert_to_athana_feedback_model import convert_to_athana_feedback_model
from module_modeling_llm.utils.get_exercise_model import get_exercise_model


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
async def suggest_feedback(exercise: Exercise, submission: Submission, is_graded: bool, module_config: Configuration) -> List[Feedback]:
    logger.info("suggest_feedback: Suggestions for submission %d of exercise %d were requested", submission.id,
                exercise.id)
    
    # First, we convert the incoming exercise and submission to our internal models and textual representations
    exercise_model = get_exercise_model(exercise, submission)

    # Next, we retrieve or generate the structured grading instructions for the exercise
    structured_grading_instructions = await get_structured_grading_instructions(
        exercise_model, module_config.approach, exercise.grading_instructions, exercise.grading_criteria, module_config.debug
    )

    # Finally, we generate feedback suggestions for the submission
    feedback = await generate_suggestions(
        exercise_model, structured_grading_instructions, module_config.approach, module_config.debug
    )

    # If the submission is not graded (Student is requesting feedback), we reformulate the feedback to not give away the solution
    if is_graded is False:
        feedback = await filter_feedback(exercise_model, feedback, module_config.approach, module_config.debug)

    return convert_to_athana_feedback_model(feedback, exercise_model, structured_grading_instructions.criteria)



if __name__ == "__main__":
    nltk.download("punkt_tab")
    tiktoken.get_encoding("cl100k_base")
    app.start()
