from athena import Exercise
from .endpoints.modules_endpoint import get_modules
from .module import Module


def resolve_module(exercise: Exercise) -> Module:
    """
    Find a module fitting for the given exercise.
    """
    for module in get_modules():
        if module.type == exercise.type:
            return module
    raise ValueError(f"No module found for exercise {exercise.id}.")
