import dotenv

from .basic_approach import generate_suggestions as basic
from .divide_and_conquer import generate_suggestions as divide_and_conquer
from .self_consistency import generate_suggestions as self_consistency
from .cot_prev_submission import generate_suggestions as cot_prev_submission
from .llm_as_profiler import generate_suggestions as llm_as_profiler

__all__ = [
    "basic",
    "divide_and_conquer",
    "self_consistency",
    "cot_prev_submission",
    "llm_as_profiler"
]

dotenv.load_dotenv(override=True)