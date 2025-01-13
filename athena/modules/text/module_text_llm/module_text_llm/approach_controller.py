from typing import List
from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig

async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    from module_text_llm import strategyFactory

    strategy = strategyFactory.get_strategy(config)
    return await strategy.generate_suggestions(exercise, submission, config, debug)
