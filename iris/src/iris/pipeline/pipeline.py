from __future__ import annotations

import logging
from abc import ABCMeta, abstractmethod
from typing import ClassVar, List

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.config import settings
from iris.domain.variant.abstract_variant import AbstractVariant
from iris.domain.variant.variant import Dep, Variant
from iris.llm.llm_configuration import resolve_role_models, role_requirements

logger = logging.getLogger(__name__)


def _get_dep_roles(pipeline_id: str, variant_id: str) -> set[str]:
    """Discover a dependency pipeline's roles from the config."""
    pipeline_cfg = settings.llm_configuration.get(pipeline_id)
    if pipeline_cfg is None:
        logger.warning(
            "Dependency pipeline '%s' not found in llm_configuration", pipeline_id
        )
        return set()
    variant_cfg = pipeline_cfg.get(variant_id)
    if variant_cfg is None:
        logger.warning(
            "Variant '%s' not found for dependency pipeline '%s' in llm_configuration",
            variant_id,
            pipeline_id,
        )
        return set()
    return set(variant_cfg.keys())


class Pipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    PIPELINE_ID: ClassVar[str] = ""
    ROLES: ClassVar[set[str]] = set()
    VARIANT_DEFS: ClassVar[list[tuple[str, str, str]]] = []
    DEPENDENCIES: ClassVar[list[Dep]] = []

    implementation_id: str
    tokens: List[TokenUsageDTO]

    def __init__(self, implementation_id=None):
        self.implementation_id = implementation_id

    def __str__(self):
        return f"{self.__class__.__name__}"

    def __repr__(self):
        return f"{self.__class__.__name__}"

    @abstractmethod
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
    def get_variants(cls) -> List[AbstractVariant]:
        """
        Returns a list of all variants for this pipeline.

        Default implementation derives variants from PIPELINE_ID, ROLES,
        VARIANT_DEFS, and DEPENDENCIES class attributes. Subclasses can
        override for custom behaviour.

        Pipelines with ROLES = set() (orchestrators) don't need their own
        llm_configuration entry — they derive all required models from
        DEPENDENCIES.
        """
        if not cls.VARIANT_DEFS:
            return []

        variants: list[Variant] = []
        for vid, name, desc in cls.VARIANT_DEFS:
            role_models: dict[str, dict[str, str]] = {}
            for role in cls.ROLES:
                role_models[role] = resolve_role_models(cls.PIPELINE_ID, vid, role)

            required: set[str] = set()
            for rm in role_models.values():
                required |= set(rm.values())

            for dep in cls.DEPENDENCIES:
                dep_vid = vid if dep.variant == "same" else dep.variant
                for dep_role in _get_dep_roles(dep.pipeline_id, dep_vid):
                    required |= role_requirements(dep.pipeline_id, dep_vid, dep_role)

            variants.append(
                Variant(
                    variant_id=vid,
                    name=name,
                    description=desc,
                    role_models=role_models,
                    required_model_ids=required,
                )
            )
        return variants
