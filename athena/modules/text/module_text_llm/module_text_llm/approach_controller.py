from typing import List, Optional
import inspect

from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig
from module_text_llm import get_strategy_factory 
from athena.schemas import LearnerProfile


async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, *, debug: bool, is_graded: bool,
                               learner_profile: Optional[LearnerProfile] = None, latest_submission: Optional[Submission] = None) -> List[Feedback]:
    strategy_factory = get_strategy_factory(ApproachConfig)
    strategy = strategy_factory.get_strategy(config)
    # Introspect the signature to filter kwargs
    sig = inspect.signature(strategy.generate_suggestions)
    filtered_kwargs = {}
    for k, v in {'learner_profile': learner_profile, 'latest_submission': latest_submission}.items():
        if k in sig.parameters:
            filtered_kwargs[k] = v
    return await strategy.generate_suggestions(exercise, submission, config, debug=debug, is_graded=is_graded, **filtered_kwargs)
