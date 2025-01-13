from typing import List
from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig

async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    # Importing the strategy_factory here to avoid circular imports with ApproachConfig
    # pylint: disable=import-outside-toplevel
    from module_text_llm import strategy_factory 

    strategy = strategy_factory.get_strategy(config)
    return await strategy.generate_suggestions(exercise, submission, config, debug)
