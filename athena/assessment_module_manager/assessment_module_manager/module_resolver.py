from .module import Module, get_module_list
from athena import Exercise


def resolve_module(exercise: Exercise) -> Module:
    """
    Find a module fitting for the given exercise.
    """
    for module in get_module_list():
        if module.type == exercise.type:
            return module
    raise ValueError(f"No module found for exercise {exercise.id}.")
