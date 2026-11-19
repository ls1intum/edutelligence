from .errors import InfiniteTypeError, TypeMismatchError
from .substitution import Substitution
from .types import (
    Monotype,
    TBool,
    TFunction,
    TInt,
    TPair,
    TVariable,
    free_type_variables,
)


def unify(left: Monotype, right: Monotype) -> Substitution:
    if left == right:
        return Substitution()
    if isinstance(left, TVariable):
        return _bind(left, right)
    if isinstance(right, TVariable):
        return _bind(right, left)
    if isinstance(left, TFunction) and isinstance(right, TFunction):
        argument = unify(left.argument, right.argument)
        result = unify(
            argument.apply_type(left.result), argument.apply_type(right.result)
        )
        return result.compose(argument)
    if isinstance(left, TPair) and isinstance(right, TPair):
        first = unify(left.left, right.left)
        second = unify(first.apply_type(left.right), first.apply_type(right.right))
        return second.compose(first)
    if isinstance(left, (TInt, TBool)) and isinstance(right, type(left)):
        return Substitution()
    raise TypeMismatchError(f"cannot unify {left!r} with {right!r}")


def _bind(variable: TVariable, value: Monotype) -> Substitution:
    if variable.identifier in free_type_variables(value):
        raise InfiniteTypeError(f"infinite type for {variable!r}")
    return Substitution({variable.identifier: value})
