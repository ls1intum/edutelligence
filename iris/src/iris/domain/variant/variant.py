from __future__ import annotations

from dataclasses import dataclass

from iris.domain.variant.abstract_variant import AbstractVariant


@dataclass(frozen=True)
class Dep:
    """Declares a pipeline dependency for variant resolution."""

    pipeline_id: str
    variant: str = (
        "default"  # "same" = inherit parent variant_id, otherwise literal variant_id
    )


class Variant(AbstractVariant):
    """Generic variant that replaces all concrete variant classes.

    Stores role-based model mappings (role -> {"local": id, "cloud": id})
    and the full set of required model IDs (own + transitive deps).
    """

    _role_models: dict[str, dict[str, str]]
    _required_model_ids: set[str]

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        role_models: dict[str, dict[str, str]],
        required_model_ids: set[str],
    ):
        super().__init__(variant_id=variant_id, name=name, description=description)
        self._role_models = role_models
        self._required_model_ids = required_model_ids

    def model(self, role: str, local: bool) -> str:
        """Return the model ID for the given role and environment."""
        env = "local" if local else "cloud"
        try:
            return self._role_models[role][env]
        except KeyError as exc:
            available = list(self._role_models.keys())
            raise KeyError(
                f"Role '{role}' ({env}) not found in variant '{self.id}'. "
                f"Available roles: {available}"
            ) from exc

    def required_models(self) -> set[str]:
        return set(self._required_model_ids)
