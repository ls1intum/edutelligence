from athena import ExerciseTypeVar
from .list_modules import list_modules
from .module import Module


def resolve_module(exercise: ExerciseTypeVar) -> Module:
    """
    Find an available module fitting for the given exercise.
    """
    for module in list_modules():
        if module.type == exercise.type:
            return module
    raise ValueError(f"No module found for exercise {exercise.id}.")
