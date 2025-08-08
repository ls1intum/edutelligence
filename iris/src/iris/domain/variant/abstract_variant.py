from abc import ABC, abstractmethod

from ..feature_dto import FeatureDTO


class AbstractVariant(ABC):
    id: str
    name: str
    description: str

    def __init__(self, id: str, name: str, description: str):
        self.id = id
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
            id=self.id,
            name=self.name,
            description=self.description,
        )


class AbstractAgentVariant(AbstractVariant):
    agent_model: str

    def __init__(self, id: str, name: str, description: str, agent_model: str):
        super().__init__(id=id, name=name, description=description)
        self.agent_model = agent_model

    def required_models(self) -> set[str]:
        return {self.agent_model}
