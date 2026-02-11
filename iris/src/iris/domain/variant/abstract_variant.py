from abc import ABC, abstractmethod
from typing import TypeVar

from ..feature_dto import FeatureDTO

_V = TypeVar("_V", bound="AbstractVariant")


def find_variant(variants: list[_V], variant_id: str) -> _V:
    """Find a variant by ID from a list of variants.

    Raises:
        ValueError: If no variant matches the given ID.
    """
    for v in variants:
        if v.id == variant_id:
            return v
    available = [v.id for v in variants]
    available_str = ", ".join(available)
    raise ValueError(f"Unknown variant: {variant_id}. Available: {available_str}")


class AbstractVariant(ABC):
    """Abstract base class for all variant configurations."""

    variant_id: str
    name: str
    description: str

    def __init__(self, variant_id: str, name: str, description: str):
        self.variant_id = variant_id
        self.id = variant_id  # Keep for backward compatibility
        self.name = name
        self.description = description

    @abstractmethod
    def required_models(self) -> set[str]:
        """
        Abstract method to return a set of required models for the variant.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def feature_dto(self) -> FeatureDTO:
        """
        Returns a FeatureDTO representing the agent variant.
        """
        return FeatureDTO(
            id=self.variant_id,
            name=self.name,
            description=self.description,
        )
