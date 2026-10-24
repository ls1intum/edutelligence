from dataclasses import dataclass, field

from .errors import UnknownVariableError
from .scheme import Scheme
from .substitution import Substitution


@dataclass(frozen=True, slots=True)
class TypeEnvironment:
    """Associate term variables with polymorphic type schemes."""

    bindings: dict[str, Scheme] = field(default_factory=dict)

    def lookup(self, name: str) -> Scheme:
        try:
            return self.bindings[name]
        except KeyError as error:
            raise UnknownVariableError(name) from error

    def extend(self, name: str, scheme: Scheme) -> "TypeEnvironment":
        return TypeEnvironment({**self.bindings, name: scheme})

    def apply(self, substitution: Substitution) -> "TypeEnvironment":
        return TypeEnvironment(
            {name: scheme.apply(substitution) for name, scheme in self.bindings.items()}
        )

    def free_type_variables(self) -> set[int]:
        result: set[int] = set()
        for scheme in self.bindings.values():
            result.update(scheme.free_type_variables())
        return result
