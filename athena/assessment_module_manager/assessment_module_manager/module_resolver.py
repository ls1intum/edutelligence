from athena import Exercise
from .endpoints.module import get_module_list
from .module import Module


def resolve_module(exercise: Exercise) -> Module:
    """
    Find a module fitting for the given exercise.
    """
    for module in get_module_list():
        if module.type == exercise.type:
            return module
    raise ValueError(f"No module found for exercise {exercise.id}.")
