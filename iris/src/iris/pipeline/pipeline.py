from abc import ABCMeta, abstractmethod
from typing import Generic, List, TypeVar

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.variant.abstract_variant import AbstractVariant

VARIANT = TypeVar("VARIANT", bound=AbstractVariant)


class Pipeline(Generic[VARIANT], metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    implementation_id: str
    tokens: List[TokenUsageDTO]

    def __init__(self, implementation_id=None):
        self.implementation_id = implementation_id

    def __str__(self):
        return f"{self.__class__.__name__}"

    def __repr__(self):
        return f"{self.__class__.__name__}"

    @abstractmethod
    def __call__(self, *args, **kwargs):
        """
        Extracts the required parameters from the args/kwargs and runs the pipeline.
        Subclasses should override with their specific signature.
        """
        raise NotImplementedError("Subclasses must implement the __call__ method.")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "__call__" not in cls.__dict__:
            raise NotImplementedError(
                "Subclasses of Pipeline interface must implement the __call__ method."
            )

    def _append_tokens(self, tokens: TokenUsageDTO, pipeline: PipelineEnum) -> None:
        tokens.pipeline = pipeline
        self.tokens.append(tokens)

    @classmethod
    @abstractmethod
    def get_variants(cls) -> List[VARIANT]:
        """
        Returns a list of all variants for this pipeline.
        This method should be implemented by subclasses to provide specific variants.

        Returns:
            List of variants available for this pipeline.
        """
        raise NotImplementedError("Subclasses must implement the get_variants method.")
