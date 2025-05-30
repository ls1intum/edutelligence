from typing import List, Optional

from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig
from athena.schemas.learner_profile import LearnerProfile
import inspect


import inspect
from typing import Any, Dict, List, Optional

from athena.text import Exercise, Submission
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
    # Inspect the signature to see if learner_profile is supported
    sig = inspect.signature(config.generate_suggestions)

    kwargs: Dict[str, Any] = {
        "debug": debug,
        "is_graded": is_graded,
    }

    if "learner_profile" in sig.parameters:
        kwargs["learner_profile"] = learner_profile

    return await config.generate_suggestions(
        exercise,
        submission,
        config,
        **kwargs,
    )
