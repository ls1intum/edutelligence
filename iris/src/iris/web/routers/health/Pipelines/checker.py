from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Set

from iris.domain.variant.abstract_variant import AbstractVariant
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.registery import PIPELINE_BY_FEATURE


def _get_default_variant(variants: Iterable) -> AbstractVariant | None:
    variants = list(variants)
    return next((v for v in variants if getattr(v, "id", None) == "default"), None)


def _get_advanced_required_models(variants: Iterable[AbstractVariant]) -> set[str]:
    return {
        m
        for v in variants
        if getattr(v, "id", None) != "default"
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


def evaluate_feature(feature: Features, available: Set[str]) -> FeatureResult:
    pipeline_cls = PIPELINE_BY_FEATURE.get(feature)
    if pipeline_cls is None:
        return FeatureResult(
            feature, wired=False, has_default=False, missing_models=frozenset()
        )
    try:
        variants: Sequence[AbstractVariant] = pipeline_cls.get_variants()
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
    # Find all missing models
    all_missing = all_required - available
    default_available = required_default - available == set()
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
