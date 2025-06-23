from abc import ABCMeta
from typing import List

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain import FeatureDTO
from iris.llm.external.model import LanguageModel


class Pipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    implementation_id: str
    tokens: List[TokenUsageDTO]

    def __init__(self, implementation_id=None):
        self.implementation_id = implementation_id

    def __str__(self):
        return f"{self.__class__.__name__}"

    def __repr__(self):
        return f"{self.__class__.__name__}"

    def __call__(self, **kwargs):
        """
        Extracts the required parameters from the kwargs runs the pipeline.
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
    def get_variants(
        cls, available_llms: List[LanguageModel]  # pylint: disable=unused-argument
    ) -> List[FeatureDTO]:
        """
        Returns available variants for this pipeline based on available LLMs.
        By default, returns a single 'default' variant.
        Pipeline subclasses can override this method to provide custom variant logic.

        Args:
            available_llms: List of available language models

        Returns:
            List of FeatureDTO objects representing available variants
        """
        return [
            FeatureDTO(
                id="default",
                name="Default Variant",
                description="Default pipeline variant.",
            )
        ]
