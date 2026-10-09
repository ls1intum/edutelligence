from dataclasses import dataclass
from typing import Callable

from .substitution import Substitution
from .types import Monotype, TVariable, free_type_variables


@dataclass(frozen=True, slots=True)
class Scheme:
    """Represent a type with variables quantified by a let binding."""

    quantified: frozenset[int]
    body: Monotype

    def free_type_variables(self) -> set[int]:
        return free_type_variables(self.body) - self.quantified

    def apply(self, substitution: Substitution) -> "Scheme":
        return Scheme(
            self.quantified,
            substitution.without(self.quantified).apply_type(self.body),
        )

    def instantiate(self, fresh: Callable[[], TVariable]) -> Monotype:
        replacements = {identifier: fresh() for identifier in sorted(self.quantified)}
        return Substitution(replacements).apply_type(self.body)
