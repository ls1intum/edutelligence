from typing import List, Optional

from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig
from module_text_llm import get_strategy_factory 
from athena.schemas import LearnerProfile, Result


async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, *, debug: bool, is_graded: bool,
                               learner_profile: Optional[LearnerProfile] = None, result: Optional[Result]) -> List[Feedback]:
    strategy_factory = get_strategy_factory(ApproachConfig)
    strategy = strategy_factory.get_strategy(config)
    return await strategy.generate_suggestions(exercise, submission, config, debug=debug, is_graded=is_graded,
                                               learner_profile=learner_profile, result=result)
