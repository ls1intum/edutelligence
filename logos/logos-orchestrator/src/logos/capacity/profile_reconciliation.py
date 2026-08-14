"""Cross-node reconciliation of self-reported model profiles.

Every worker node calibrates the models it can host and reports a profile:
resident footprint, KV budget, sleeping residual.  Those figures are the sole
input to placement, and the orchestrator has no independent way to measure them.
That is tolerable as long as the figures agree with each other.

They do not always agree.  In the production fleet, the same model calibrated on
different nodes has been observed with base residencies differing by a factor of
five -- for a model whose weights cannot account for either figure.  The cause is
not noise: ``base_residency_mb`` carries different semantics depending on
``residency_source``, and worker builds are updated per node rather than
fleet-wide, so two nodes can report the same field under the same label meaning
two different things.

A single node cannot detect this; the disagreement only exists across nodes.
This module performs that comparison and turns a silent inconsistency into an
operational signal.  It changes no placement decision on its own -- it reports.

Detected conditions:

``kv_inclusion_skew``
    Node A's base residency minus its KV budget lands within tolerance of node
    B's base residency.  That arithmetic identity is the signature of one node
    including the KV budget in the residency figure while the other excludes it.
    This is the highest-confidence finding: it names the defect, not just the
    disagreement.

``footprint_disagreement``
    Base residencies for the same model differ by more than a tolerated ratio
    without matching the KV-inclusion signature.  Cause unknown -- could be
    different quantisation, different tensor-parallel degree, or a calibration
    that ran under memory pressure.

``uncalibrated_majority``
    Most nodes hosting the model have never measured it.  Placement decisions
    for that model rest on defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# A model's residency figures may legitimately differ across nodes -- different
# accelerators, different tensor-parallel degrees.  Beyond this ratio the
# difference is too large to be explained that way.
DISAGREEMENT_RATIO = 1.5

# How close (relative) base_A - kv_A must land to base_B for the difference to be
# attributed to KV inclusion rather than coincidence.
KV_INCLUSION_TOLERANCE = 0.10

# Below this many megabytes the figures are too small for ratios to be meaningful.
MIN_MEANINGFUL_MB = 256.0


@dataclass(frozen=True)
class NodeProfile:
    """One node's declaration about one model."""

    provider_id: int
    model_name: str
    base_residency_mb: Optional[float] = None
    kv_budget_mb: Optional[float] = None
    loaded_vram_mb: Optional[float] = None
    tensor_parallel_size: Optional[int] = None
    residency_source: Optional[str] = None
    measurement_count: int = 0

    @property
    def is_measured(self) -> bool:
        return self.measurement_count > 0 and self.residency_source in ("calibrated", "measured")


@dataclass
class Inconsistency:
    """A disagreement between nodes about the same model."""

    model_name: str
    kind: str
    severity: str  # "high" | "medium" | "low"
    detail: str
    provider_ids: List[int] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "provider_ids": list(self.provider_ids),
            "evidence": dict(self.evidence),
        }


def _usable(profile: NodeProfile) -> bool:
    base = profile.base_residency_mb
    return base is not None and base >= MIN_MEANINGFUL_MB


def _kv_inclusion_match(high: NodeProfile, low: NodeProfile) -> Optional[float]:
    """Return the relative error if ``high`` looks like ``low`` plus its KV budget.

    ``None`` when the identity does not hold, when the KV budget is unknown, or
    when it is too small to explain the gap.
    """
    if high.kv_budget_mb is None or high.kv_budget_mb <= 0:
        return None
    if high.base_residency_mb is None or low.base_residency_mb is None:
        return None

    implied = high.base_residency_mb - high.kv_budget_mb
    if implied <= 0:
        return None
    reference = low.base_residency_mb
    if reference <= 0:
        return None
    return abs(implied - reference) / reference


def reconcile_model(profiles: Iterable[NodeProfile]) -> List[Inconsistency]:
    """Compare every node's declaration for a single model."""
    profiles = [p for p in profiles]
    if len(profiles) < 2:
        return []

    model_name = profiles[0].model_name
    findings: List[Inconsistency] = []

    measured = [p for p in profiles if p.is_measured and _usable(p)]
    if len(measured) < 2:
        if profiles and not any(p.is_measured for p in profiles):
            findings.append(
                Inconsistency(
                    model_name=model_name,
                    kind="uncalibrated_majority",
                    severity="low",
                    detail=(f"no node hosting {model_name} has measured it; " "placement decisions rest on defaults"),
                    provider_ids=sorted(p.provider_id for p in profiles),
                    evidence={"hosting_nodes": len(profiles), "measured_nodes": 0},
                )
            )
        return findings

    ordered = sorted(measured, key=lambda p: float(p.base_residency_mb or 0.0))
    lowest, highest = ordered[0], ordered[-1]
    low_mb = float(lowest.base_residency_mb or 0.0)
    high_mb = float(highest.base_residency_mb or 0.0)
    if low_mb <= 0:
        return findings

    ratio = high_mb / low_mb
    if ratio <= DISAGREEMENT_RATIO:
        return findings

    relative_error = _kv_inclusion_match(highest, lowest)
    if relative_error is not None and relative_error <= KV_INCLUSION_TOLERANCE:
        findings.append(
            Inconsistency(
                model_name=model_name,
                kind="kv_inclusion_skew",
                severity="high",
                detail=(
                    f"provider {highest.provider_id} reports {high_mb:.0f} MB base residency for "
                    f"{model_name} while provider {lowest.provider_id} reports {low_mb:.0f} MB; "
                    f"the difference matches provider {highest.provider_id}'s KV budget "
                    f"({highest.kv_budget_mb:.0f} MB), so one build includes the KV cache in the "
                    "residency figure and the other does not"
                ),
                provider_ids=[lowest.provider_id, highest.provider_id],
                evidence={
                    "high_provider": highest.provider_id,
                    "high_base_mb": high_mb,
                    "high_kv_budget_mb": highest.kv_budget_mb,
                    "low_provider": lowest.provider_id,
                    "low_base_mb": low_mb,
                    "implied_after_removing_kv_mb": high_mb - float(highest.kv_budget_mb or 0.0),
                    "relative_error": relative_error,
                    "ratio": ratio,
                },
            )
        )
        return findings

    findings.append(
        Inconsistency(
            model_name=model_name,
            kind="footprint_disagreement",
            severity="medium",
            detail=(
                f"{model_name} base residency differs {ratio:.1f}x across nodes "
                f"({low_mb:.0f} MB on provider {lowest.provider_id} vs "
                f"{high_mb:.0f} MB on provider {highest.provider_id}); "
                "placement decisions on these nodes are not comparable"
            ),
            provider_ids=[lowest.provider_id, highest.provider_id],
            evidence={
                "low_provider": lowest.provider_id,
                "low_base_mb": low_mb,
                "low_tp": lowest.tensor_parallel_size,
                "high_provider": highest.provider_id,
                "high_base_mb": high_mb,
                "high_tp": highest.tensor_parallel_size,
                "ratio": ratio,
            },
        )
    )
    return findings


def reconcile(profiles: Iterable[NodeProfile]) -> List[Inconsistency]:
    """Group declarations by model and reconcile each group."""
    by_model: Dict[str, List[NodeProfile]] = {}
    for profile in profiles:
        by_model.setdefault(profile.model_name, []).append(profile)

    findings: List[Inconsistency] = []
    for model_profiles in by_model.values():
        findings.extend(reconcile_model(model_profiles))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (severity_order.get(f.severity, 3), f.model_name))
    return findings


def log_findings(findings: List[Inconsistency]) -> None:
    """Emit findings at a level matching their severity."""
    for finding in findings:
        if finding.severity == "high":
            logger.warning("Model profile inconsistency [%s]: %s", finding.kind, finding.detail)
        elif finding.severity == "medium":
            logger.warning("Model profile disagreement [%s]: %s", finding.kind, finding.detail)
        else:
            logger.info("Model profile note [%s]: %s", finding.kind, finding.detail)


def rows_to_profiles(rows: Iterable[Any]) -> List[NodeProfile]:
    """Build profiles from ``model_profiles`` table rows (mappings or tuples)."""
    out: List[NodeProfile] = []
    for row in rows:
        data = row._mapping if hasattr(row, "_mapping") else row
        try:
            out.append(
                NodeProfile(
                    provider_id=int(data["provider_id"]),
                    model_name=str(data["model_name"]),
                    base_residency_mb=_as_float(data.get("base_residency_mb")),
                    kv_budget_mb=_as_float(data.get("kv_budget_mb")),
                    loaded_vram_mb=_as_float(data.get("loaded_vram_mb")),
                    tensor_parallel_size=_as_int(data.get("tensor_parallel_size")),
                    residency_source=data.get("residency_source"),
                    measurement_count=_as_int(data.get("measurement_count")) or 0,
                )
            )
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping unparseable model_profiles row", exc_info=True)
    return out


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
