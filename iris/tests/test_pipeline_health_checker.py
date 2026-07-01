from __future__ import annotations

from enum import Enum

import pytest

from iris.config import settings
from iris.domain.variant.variant import Variant
from iris.pipeline.rewriting_pipeline import RewritingPipeline
from iris.web.routers.health.Pipelines import checker
from iris.web.routers.health.Pipelines.checker import (
    _get_baseline_variant,
    _get_non_baseline_required_models,
    evaluate_feature,
)
from iris.web.routers.health.Pipelines.features import Features


def test_rewriting_pipeline_health_baseline_is_problem_statement():
    # Pin the specific override so accidentally removing it surfaces here
    # rather than only in the health endpoint at deploy time.
    assert RewritingPipeline.HEALTH_BASELINE_VARIANT_ID == "problem_statement"
    declared_variant_ids = {vid for vid, _, _ in RewritingPipeline.VARIANT_DEFS}
    assert (
        RewritingPipeline.HEALTH_BASELINE_VARIANT_ID in declared_variant_ids
    ), "HEALTH_BASELINE_VARIANT_ID must point at a declared variant"


def _make_variant(variant_id: str, required: set[str]) -> Variant:
    return Variant(
        variant_id=variant_id,
        name=variant_id,
        description="",
        role_models={},
        required_model_ids=required,
    )


def test_get_baseline_variant_returns_match_for_custom_id():
    variants = [
        _make_variant("faq", {"m1"}),
        _make_variant("problem_statement", {"m2"}),
    ]
    baseline = _get_baseline_variant(variants, "problem_statement")
    assert baseline is not None
    assert baseline.id == "problem_statement"


def test_get_baseline_variant_returns_none_when_id_absent():
    variants = [_make_variant("faq", {"m1"})]
    assert _get_baseline_variant(variants, "default") is None


def test_get_non_baseline_required_models_exact_equality():
    # A variant id that *contains* the substring "default" but is not equal
    # must be treated as non-baseline. The previous substring-based check
    # would have wrongly excluded "default_v2" from the non-baseline set.
    variants = [
        _make_variant("default", {"m_baseline"}),
        _make_variant("default_v2", {"m_v2"}),
        _make_variant("advanced", {"m_advanced"}),
    ]
    non_baseline = _get_non_baseline_required_models(variants, "default")
    assert non_baseline == {"m_v2", "m_advanced"}


class _FakeFeature(str, Enum):
    FAKE = "FAKE"


class _FakePipelineBase:
    """Fake pipeline whose get_variants() is controlled by class attributes."""

    HEALTH_BASELINE_VARIANT_ID = "default"
    _VARIANTS: tuple[Variant, ...] = ()

    @classmethod
    def get_variants(cls) -> list[Variant]:
        return list(cls._VARIANTS)


def _evaluate_with_fake(
    monkeypatch: pytest.MonkeyPatch,
    pipeline_cls: type,
    available: set[str],
):
    monkeypatch.setattr(
        checker, "PIPELINE_BY_FEATURE", {_FakeFeature.FAKE: pipeline_cls}
    )
    return evaluate_feature(_FakeFeature.FAKE, available)


def test_evaluate_feature_with_custom_baseline_passes(monkeypatch):
    class P(_FakePipelineBase):
        HEALTH_BASELINE_VARIANT_ID = "problem_statement"
        _VARIANTS = (
            _make_variant("faq", {"m_faq"}),
            _make_variant("problem_statement", {"m_ps"}),
        )

    result = _evaluate_with_fake(monkeypatch, P, available={"m_faq", "m_ps"})
    assert result.wired is True
    assert result.has_default is True
    assert result.missing_models == frozenset()
    assert result.ok is True


def test_evaluate_feature_rewriting_uses_problem_statement_baseline(monkeypatch):
    monkeypatch.setattr(settings, "local_llm_enabled", True)
    monkeypatch.setattr(
        settings,
        "llm_configuration",
        {
            "rewriting_pipeline": {
                "faq": {
                    "rewriting": {"local": "m_faq", "cloud": "m_faq"},
                    "consistency": {"local": "m_faq", "cloud": "m_faq"},
                },
                "problem_statement": {
                    "rewriting": {"local": "m_ps", "cloud": "m_ps"},
                    "consistency": {"local": "m_ps", "cloud": "m_ps"},
                },
            }
        },
    )

    result = evaluate_feature(Features.REWRITING, {"m_faq", "m_ps"})

    assert result.wired is True
    assert result.has_default is True
    assert result.missing_models == frozenset()
    assert result.ok is True


def test_evaluate_feature_baseline_model_missing_flips_has_default(monkeypatch):
    class P(_FakePipelineBase):
        HEALTH_BASELINE_VARIANT_ID = "problem_statement"
        _VARIANTS = (
            _make_variant("faq", {"m_faq"}),
            _make_variant("problem_statement", {"m_ps"}),
        )

    result = _evaluate_with_fake(monkeypatch, P, available={"m_faq"})
    assert result.wired is True
    assert result.has_default is False
    assert "m_ps" in result.missing_models


def test_evaluate_feature_non_baseline_missing_keeps_has_default(monkeypatch):
    class P(_FakePipelineBase):
        HEALTH_BASELINE_VARIANT_ID = "default"
        _VARIANTS = (
            _make_variant("default", {"m_default"}),
            _make_variant("advanced", {"m_advanced"}),
        )

    result = _evaluate_with_fake(monkeypatch, P, available={"m_default"})
    assert result.wired is True
    assert result.has_default is True
    assert result.missing_models == frozenset({"m_advanced"})
    # has_default is True but missing_models is non-empty → not "ok"
    assert result.ok is False


def test_evaluate_feature_missing_baseline_variant_reports_expected_id(monkeypatch):
    class P(_FakePipelineBase):
        HEALTH_BASELINE_VARIANT_ID = "problem_statement"
        _VARIANTS = (_make_variant("faq", {"m_faq"}),)

    result = _evaluate_with_fake(monkeypatch, P, available={"m_faq"})
    assert result.wired is True
    assert result.has_default is False
    assert result.missing_models == frozenset(
        {"No baseline variant found (expected variant id: 'problem_statement')"}
    )
