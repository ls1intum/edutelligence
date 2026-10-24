from dataclasses import dataclass, field

from .types import Monotype, TFunction, TPair, TVariable


@dataclass(frozen=True, slots=True)
class Substitution:
    """Map type variables to types and combine mappings from inference steps."""

    mapping: dict[int, Monotype] = field(default_factory=dict)

    def apply_type(self, value: Monotype) -> Monotype:
        if isinstance(value, TVariable) and value.identifier in self.mapping:
            return self.mapping[value.identifier]
        if isinstance(value, TFunction):
            return TFunction(
                self.apply_type(value.argument), self.apply_type(value.result)
            )
        if isinstance(value, TPair):
            return TPair(self.apply_type(value.left), self.apply_type(value.right))
        return value

    def without(self, identifiers: frozenset[int]) -> "Substitution":
        return Substitution(
            {
                key: value
                for key, value in self.mapping.items()
                if key not in identifiers
            }
        )

    def compose(self, earlier: "Substitution") -> "Substitution":
        combined = dict(self.mapping)
        combined.update(earlier.mapping)
        return Substitution(combined)
