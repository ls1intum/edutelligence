from typing import List
from athena.text import Exercise, Submission, Feedback, get_stored_feedback,get_stored_feedback_suggestions
from module_text_llm.approach_config import ApproachConfig
from athena.logger import logger
async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    # Importing the strategy_factory here to avoid circular imports with ApproachConfig
    # pylint: disable=import-outside-toplevel
    from module_text_llm import strategy_factory 

    strategy = strategy_factory.get_strategy(config)
    result =  await strategy.generate_suggestions(exercise, submission, config, debug)
    stored_feedback = list(get_stored_feedback_suggestions(exercise.id, submission.id))
    ai_feedback = [feedback for feedback in stored_feedback]
    logger.info(f"Stored feedback: {ai_feedback} for exercise {exercise.id} and submission {submission.id}")
    return result