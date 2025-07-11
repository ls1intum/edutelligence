from typing import Any, Dict, List, Optional
from athena.text import Exercise, Submission, Feedback
from athena.schemas.learner_profile import LearnerProfile
import inspect

from module_text_llm.registry import APPROACH_IMPLEMENTATIONS
from module_text_llm.approach_config import ApproachConfig

async def generate_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: ApproachConfig,
    *,
    debug: bool,
    is_graded: bool,
    learner_profile: Optional[LearnerProfile] = None,
) -> List[Feedback]:
    implementation_func = APPROACH_IMPLEMENTATIONS.get(config.type)
    if implementation_func is None:
        raise NotImplementedError(
            f"Approach type '{config.type}' has not been registered. "
            "Ensure the module is imported in module_text_llm/__init__.py."
        )

    sig = inspect.signature(implementation_func)
    
    kwargs: Dict[str, Any] = {
        "debug": debug,
        "is_graded": is_graded,
    }

    # TODO: Latest submission

    if "learner_profile" in sig.parameters:
        kwargs["learner_profile"] = learner_profile

    return await implementation_func(
        exercise,
        submission,
        config,
        **kwargs,
    )
