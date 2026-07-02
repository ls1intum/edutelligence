from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Set

from iris.domain.variant.abstract_variant import AbstractVariant
from iris.llm.llm_configuration import LlmConfigurationError
from iris.llm.llm_requirements import missing_llm_requirements
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.registery import PIPELINE_BY_FEATURE


def _get_baseline_variant(
    variants: Iterable[AbstractVariant], baseline_id: str
) -> AbstractVariant | None:
    return next((v for v in variants if getattr(v, "id", None) == baseline_id), None)


def _get_non_baseline_required_models(
    variants: Iterable[AbstractVariant], baseline_id: str
) -> set[str]:
    return {
        m
        for v in variants
        if getattr(v, "id", "") != baseline_id
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

    baseline_id = getattr(pipeline_cls, "HEALTH_BASELINE_VARIANT_ID", "default")
    baseline = _get_baseline_variant(variants, baseline_id)
    if baseline is None:
        # Baseline variant not declared on this pipeline. Skip non-baseline
        # checks: we can't validate models for a baseline we don't have.
        return FeatureResult(
            feature,
            wired=True,
            has_default=False,
            missing_models=frozenset(
                {f"No baseline variant found (expected variant id: '{baseline_id}')"}
            ),
        )
    required_baseline = baseline.required_models()
    required_non_baseline = _get_non_baseline_required_models(variants, baseline_id)

    all_required = required_baseline.union(required_non_baseline)
    all_missing = missing_llm_requirements(
        all_required,
        available_ids=set(available_ids),
    )
    baseline_missing = missing_llm_requirements(
        required_baseline,
        available_ids=set(available_ids),
    )
    baseline_available = not baseline_missing
    if not baseline_available:
        return FeatureResult(
            feature,
            wired=True,
            has_default=False,
            missing_models=frozenset(all_missing),
        )

    return FeatureResult(
        feature, wired=True, has_default=True, missing_models=frozenset(all_missing)
    )
