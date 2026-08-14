"""Tests for cross-node model-profile reconciliation.

The headline cases use figures taken verbatim from the production fleet, where
the same model was calibrated on three nodes with base residencies differing by
a factor of five.
"""

from __future__ import annotations

from logos.capacity.profile_reconciliation import (
    DISAGREEMENT_RATIO,
    Inconsistency,
    NodeProfile,
    reconcile,
    reconcile_model,
    rows_to_profiles,
)


def profile(provider_id: int, model: str, base: float | None, kv: float | None = None, **kw) -> NodeProfile:
    return NodeProfile(
        provider_id=provider_id,
        model_name=model,
        base_residency_mb=base,
        kv_budget_mb=kv,
        residency_source=kw.pop("residency_source", "calibrated"),
        measurement_count=kw.pop("measurement_count", 1),
        **kw,
    )


# ----------------------------------------------------------------------
# The production case this module exists for
# ----------------------------------------------------------------------


def test_detects_kv_inclusion_skew_from_production_figures():
    """gemma-4-E2B-it as actually recorded: 17539 MB on two nodes, 95071 on a third.

    95071 - 77824 (that node's KV budget) = 17247, within 2% of 17539.  The
    difference is not noise or hardware -- one build includes the KV cache in the
    residency figure and the other does not.
    """
    findings = reconcile_model(
        [
            profile(15, "google/gemma-4-E2B-it", 17539.0, kv=4096.0),
            profile(16, "google/gemma-4-E2B-it", 17539.0, kv=4096.0),
            profile(22, "google/gemma-4-E2B-it", 95071.0, kv=77824.0),
        ]
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "kv_inclusion_skew"
    assert finding.severity == "high"
    assert set(finding.provider_ids) == {15, 22}
    assert finding.evidence["implied_after_removing_kv_mb"] == 17247.0
    assert finding.evidence["relative_error"] < 0.05


def test_detects_kv_inclusion_skew_for_the_second_production_model():
    """gemma-4-E4B: 95713 - 72704 = 23009, against 23531 on the other nodes."""
    findings = reconcile_model(
        [
            profile(15, "google/gemma-4-E4B", 23531.0, kv=4096.0),
            profile(22, "google/gemma-4-E4B", 95713.0, kv=72704.0),
        ]
    )
    assert [f.kind for f in findings] == ["kv_inclusion_skew"]


# ----------------------------------------------------------------------
# Agreement must stay quiet
# ----------------------------------------------------------------------


def test_agreeing_nodes_produce_no_finding():
    findings = reconcile_model(
        [
            profile(15, "openai/gpt-oss-20b", 20819.0, kv=4096.0),
            profile(16, "openai/gpt-oss-20b", 20819.0, kv=4096.0),
        ]
    )
    assert findings == []


def test_small_legitimate_variation_produces_no_finding():
    """gpt-oss-120b really does differ slightly across nodes: 91203 vs 98945."""
    findings = reconcile_model(
        [
            profile(15, "openai/gpt-oss-120b", 91203.0, kv=8192.0),
            profile(22, "openai/gpt-oss-120b", 98945.0, kv=8192.0),
        ]
    )
    assert findings == [], "an 8% spread is within what hardware differences explain"


def test_a_single_node_is_never_inconsistent():
    assert reconcile_model([profile(15, "solo-model", 12345.0, kv=4096.0)]) == []


# ----------------------------------------------------------------------
# The weaker signal
# ----------------------------------------------------------------------


def test_large_disagreement_without_kv_signature_is_reported_as_unexplained():
    findings = reconcile_model(
        [
            profile(15, "some/model", 10000.0, kv=1000.0),
            profile(22, "some/model", 40000.0, kv=1000.0),
        ]
    )
    assert len(findings) == 1
    assert findings[0].kind == "footprint_disagreement"
    assert findings[0].severity == "medium"
    assert findings[0].evidence["ratio"] == 4.0


def test_disagreement_exactly_at_the_threshold_is_not_reported():
    findings = reconcile_model(
        [
            profile(15, "edge/model", 10000.0, kv=500.0),
            profile(22, "edge/model", 10000.0 * DISAGREEMENT_RATIO, kv=500.0),
        ]
    )
    assert findings == []


def test_uncalibrated_models_are_flagged_quietly():
    findings = reconcile_model(
        [
            profile(15, "never/measured", None, residency_source="cached", measurement_count=0),
            profile(16, "never/measured", None, residency_source="cached", measurement_count=0),
        ]
    )
    assert [f.kind for f in findings] == ["uncalibrated_majority"]
    assert findings[0].severity == "low"


def test_profiles_below_the_meaningful_floor_are_ignored():
    """Tiny figures make ratios meaningless; they must not generate noise."""
    findings = reconcile_model(
        [
            profile(15, "tiny/model", 10.0, kv=1.0),
            profile(22, "tiny/model", 200.0, kv=1.0),
        ]
    )
    assert findings == []


# ----------------------------------------------------------------------
# Grouping and ordering
# ----------------------------------------------------------------------


def test_reconcile_groups_by_model_and_orders_by_severity():
    findings = reconcile(
        [
            profile(15, "a/model", 10000.0, kv=1000.0),
            profile(22, "a/model", 40000.0, kv=1000.0),  # medium
            profile(15, "b/model", 17539.0, kv=4096.0),
            profile(22, "b/model", 95071.0, kv=77824.0),  # high
            profile(15, "c/model", 5000.0, kv=1000.0),
            profile(22, "c/model", 5000.0, kv=1000.0),  # none
        ]
    )
    assert [f.severity for f in findings] == ["high", "medium"]
    assert findings[0].model_name == "b/model"


def test_reconcile_handles_an_empty_fleet():
    assert reconcile([]) == []


# ----------------------------------------------------------------------
# Row parsing
# ----------------------------------------------------------------------


def test_rows_to_profiles_parses_mappings_and_tolerates_junk():
    rows = [
        {
            "provider_id": 15,
            "model_name": "x/y",
            "base_residency_mb": "1234.5",
            "kv_budget_mb": None,
            "loaded_vram_mb": 2000,
            "tensor_parallel_size": "2",
            "residency_source": "calibrated",
            "measurement_count": 3,
        },
        {"provider_id": "not-an-int", "model_name": "broken"},
    ]
    profiles = rows_to_profiles(rows)
    assert len(profiles) == 1
    assert profiles[0].provider_id == 15
    assert profiles[0].base_residency_mb == 1234.5
    assert profiles[0].tensor_parallel_size == 2
    assert profiles[0].kv_budget_mb is None


def test_inconsistency_serialises():
    finding = Inconsistency(
        model_name="m", kind="k", severity="high", detail="d", provider_ids=[1, 2], evidence={"a": 1}
    )
    assert finding.to_dict()["provider_ids"] == [1, 2]


# ----------------------------------------------------------------------
# Review follow-ups
# ----------------------------------------------------------------------


def test_kv_signature_is_found_when_it_sits_in_a_middle_pair():
    """Comparing only the extremes would miss it and report the weaker finding.

    Three nodes at 10, 20 and 40 GB: the 20/10 pair carries the KV-inclusion
    signature (20 - 10 = 10, matching the 20 GB node's KV budget), while the
    extremes 40/10 do not.
    """
    findings = reconcile_model(
        [
            profile(15, "mid/model", 10_240.0, kv=1_024.0),
            profile(16, "mid/model", 20_480.0, kv=10_240.0),
            profile(22, "mid/model", 40_960.0, kv=2_048.0),
        ]
    )
    assert [f.kind for f in findings] == ["kv_inclusion_skew"]
    assert set(findings[0].provider_ids) == {15, 16}


def test_sharding_overhead_is_not_a_disagreement():
    """Production figures: Qwen3-Embedding-8B at 21479 MB (tp=1) and 28292 (tp=2).

    Residency is a total across ranks, so a sharded lane costs roughly the same
    total plus communication buffers and duplicated embedding layers -- here 32%
    more.  That overhead is real and must not be reported as a conflict.  An
    earlier revision of this module divided residency by the rank count, which
    turned this pair into a 1.52x "disagreement" and would have flagged it.
    """
    findings = reconcile_model(
        [
            profile(15, "Qwen/Qwen3-Embedding-8B", 21_479.0, kv=6_144.0, tensor_parallel_size=1),
            profile(22, "Qwen/Qwen3-Embedding-8B", 28_292.0, kv=6_144.0, tensor_parallel_size=2),
        ]
    )
    assert findings == []


def test_kv_signature_survives_a_tensor_parallel_difference():
    """The KV budget is per rank while residency is a total, so the identity
    only closes once the budget is multiplied by the rank count.

    Here: 76000 - (30000 x 2) = 16000, matching the 16000 total reported by a
    node running the same model unsharded.  Dividing instead of multiplying --
    as an earlier revision did -- leaves 76000 - 15000 = 61000 and misses it.
    """
    findings = reconcile_model(
        [
            profile(15, "tpkv/model", 16_000.0, kv=2_000.0, tensor_parallel_size=1),
            profile(22, "tpkv/model", 76_000.0, kv=30_000.0, tensor_parallel_size=2),
        ]
    )
    assert [f.kind for f in findings] == ["kv_inclusion_skew"]
    assert findings[0].evidence["compared_in_total_units"] is True


def test_uncalibrated_majority_fires_on_a_majority_not_only_on_none():
    """One measured node out of three still leaves two placing on defaults."""
    findings = reconcile_model(
        [
            profile(15, "mostly/unmeasured", 10_000.0, kv=2_000.0),
            profile(16, "mostly/unmeasured", None, residency_source="cached", measurement_count=0),
            profile(22, "mostly/unmeasured", None, residency_source="cached", measurement_count=0),
        ]
    )
    kinds = [f.kind for f in findings]
    assert "uncalibrated_majority" in kinds
    finding = next(f for f in findings if f.kind == "uncalibrated_majority")
    assert finding.evidence["unmeasured_nodes"] == 2
    assert finding.evidence["measured_nodes"] == 1
    assert set(finding.provider_ids) == {16, 22}


def test_a_measured_minority_does_not_trigger_the_majority_finding():
    findings = reconcile_model(
        [
            profile(15, "mostly/measured", 10_000.0, kv=2_000.0),
            profile(16, "mostly/measured", 10_000.0, kv=2_000.0),
            profile(22, "mostly/measured", None, residency_source="cached", measurement_count=0),
        ]
    )
    assert [f.kind for f in findings if f.kind == "uncalibrated_majority"] == []
