from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class TVariable:
    identifier: int


@dataclass(frozen=True, slots=True)
class TInt:
    pass


@dataclass(frozen=True, slots=True)
class TBool:
    pass


@dataclass(frozen=True, slots=True)
class TFunction:
    argument: "Monotype"
    result: "Monotype"


@dataclass(frozen=True, slots=True)
class TPair:
    left: "Monotype"
    right: "Monotype"


Monotype: TypeAlias = TVariable | TInt | TBool | TFunction | TPair


def free_type_variables(value: Monotype) -> set[int]:
    if isinstance(value, TVariable):
        return {value.identifier}
    if isinstance(value, TFunction):
        return free_type_variables(value.argument) | free_type_variables(value.result)
    if isinstance(value, TPair):
        return free_type_variables(value.left) | free_type_variables(value.right)
    return set()
