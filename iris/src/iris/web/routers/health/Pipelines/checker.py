from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Set

from iris.domain.variant.abstract_variant import AbstractVariant
from iris.llm.llm_configuration import LlmConfigurationError
from iris.llm.llm_requirements import missing_llm_requirements
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.registery import PIPELINE_BY_FEATURE


def _get_default_variant(variants: Iterable) -> AbstractVariant | None:
    variants = list(variants)
    return next((v for v in variants if getattr(v, "id", None) == "default"), None)


def _get_advanced_required_models(variants: Iterable[AbstractVariant]) -> set[str]:
    return {
        m
        for v in variants
        if "default" not in getattr(v, "id", "")
        for m in v.required_models()
    }


@dataclass(frozen=True)
class FeatureResult:
    feature: Features
    wired: bool
    has_default: bool
    missing_models: frozenset[str]

    @property
    def ok(self) -> bool:
        return self.wired and self.has_default and not self.missing_models


def _missing_from_llm_configuration_error(
    error: LlmConfigurationError,
) -> frozenset[str]:
    message = str(error)
    if message.startswith("Missing llm configuration entries:"):
        lines = [line.strip() for line in message.splitlines()[1:] if line.strip()]
        if lines:
            return frozenset(lines)
    return frozenset({message})


def evaluate_feature(feature: Features, available_ids: Set[str]) -> FeatureResult:
    """
    Evaluate a feature based on configured variants and available LLMs.

    All requirements are matched against ``LanguageModel.id``.
    """
    pipeline_cls = PIPELINE_BY_FEATURE.get(feature)
    if pipeline_cls is None:
        return FeatureResult(
            feature, wired=False, has_default=False, missing_models=frozenset()
        )
    try:
        variants: list[AbstractVariant] = pipeline_cls.get_variants()
    except LlmConfigurationError as e:
        return FeatureResult(
            feature,
            wired=True,
            has_default=False,
            missing_models=_missing_from_llm_configuration_error(e),
        )
    except (TypeError, ValueError):
        return FeatureResult(
            feature, wired=True, has_default=False, missing_models=frozenset()
        )

    default = _get_default_variant(variants)
    if default is None:
        # No default variant found. Return has_default=False.
        # Per your request, we don't check advanced models if the default is missing.
        return FeatureResult(
            feature,
            wired=True,
            has_default=False,
            missing_models=frozenset({"No default variant found"}),
        )
    required_default = default.required_models()
    required_advanced = _get_advanced_required_models(variants)

    all_required = required_default.union(required_advanced)
    all_missing = missing_llm_requirements(
        all_required,
        available_ids=set(available_ids),
    )
    default_missing = missing_llm_requirements(
        required_default,
        available_ids=set(available_ids),
    )
    default_available = not default_missing
    if not default_available:
        return FeatureResult(
            feature,
            wired=True,
            has_default=False,
            missing_models=frozenset(all_missing),
        )

    return FeatureResult(
        feature, wired=True, has_default=True, missing_models=frozenset(all_missing)
    )
