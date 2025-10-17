from abc import ABC, abstractmethod

from ..feature_dto import FeatureDTO
from ...cloud_context import isCloudEnabled, localModelString


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


class AbstractAgentVariant(AbstractVariant):
    """Abstract base class for agent-based variant configurations."""

    agent_model: str

    def __init__(self, variant_id: str, name: str, description: str, agent_model: str):
        super().__init__(variant_id=variant_id, name=name, description=description)
        self.agent_model = agent_model if isCloudEnabled.get() else localModelString

    def required_models(self) -> set[str]:
        return {self.agent_model}
