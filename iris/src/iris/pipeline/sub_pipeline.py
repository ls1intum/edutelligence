from abc import ABCMeta, abstractmethod
from typing import List

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO


class SubPipeline(metaclass=ABCMeta):
    """Abstract class for all sub-pipelines"""

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
                "Subclasses of SubPipeline interface must implement the __call__ method."
            )

    def _append_tokens(self, tokens: TokenUsageDTO, pipeline: PipelineEnum) -> None:
        tokens.pipeline = pipeline
        self.tokens.append(tokens)
