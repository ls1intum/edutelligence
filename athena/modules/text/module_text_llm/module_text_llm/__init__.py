import dotenv

from .basic_approach import generate_suggestions as basic
from .chain_of_thought_approach import generate_suggestions as chain_of_thought
from .cot_learner_profile import generate_suggestions as cot_learner_profile
from .divide_and_conquer import generate_suggestions as divide_and_conquer
from .self_consistency import generate_suggestions as self_consistency

__all__ = [
    "basic",
    "chain_of_thought",
    "cot_learner_profile",
    "divide_and_conquer",
    "self_consistency",
]

dotenv.load_dotenv(override=True)