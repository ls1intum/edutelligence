import dotenv

from .basic_approach import generate_suggestions as basic
from .divide_and_conquer import generate_suggestions as divide_and_conquer
from .self_consistency import generate_suggestions as self_consistency

__all__ = [
    "basic",
    "divide_and_conquer",
    "self_consistency",
]

dotenv.load_dotenv(override=True)