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

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

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

# A profile row survives its node.  Nodes leave a federation -- withdrawn after a
# bad week, decommissioned, moved to another orchestrator -- and their rows stay
# behind, so a naive comparison keeps reporting a conflict between one live node
# and several that stopped serving months ago.  In the fleet this module was
# written for, only 23 of 89 profiles belong to a node that served traffic
# today.  Rows not refreshed within this window are treated as historical and
# excluded from comparison.
DEFAULT_MAX_PROFILE_AGE_DAYS = 30.0


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
    updated_at: Optional[datetime.datetime] = None

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


def _tp(profile: NodeProfile) -> int:
    """Tensor-parallel degree, defaulting to 1 when a node does not report it."""
    tp = profile.tensor_parallel_size
    return tp if tp and tp > 0 else 1


def _total_base_mb(profile: NodeProfile) -> float:
    """Base residency, in total-across-ranks units.

    The worker derives this from the summed per-process VRAM of every rank of
    the lane, so it is already a total and needs no conversion.  Comparing
    totals is also the right thing across differently sharded nodes: a model
    served with tensor parallelism of two occupies roughly the same total
    memory as the same model unsharded, plus communication buffers and the
    duplicated embedding layers.  That overhead is real and modest, and the
    disagreement ratio tolerates it.
    """
    base = profile.base_residency_mb
    return 0.0 if base is None else float(base)


def _total_kv_mb(profile: NodeProfile) -> float:
    """KV budget, converted from per-rank to total-across-ranks.

    Unlike the residency figure, this one is per rank: it comes from the
    engine's ``kv_cache_memory_bytes`` setting, which every rank allocates in
    full.  Mixing the two units is what makes the KV-inclusion identity fail on
    a sharded lane, so the conversion happens here and nowhere else.
    """
    kv = profile.kv_budget_mb
    return 0.0 if kv is None else float(kv) * _tp(profile)


def _usable(profile: NodeProfile) -> bool:
    base = profile.base_residency_mb
    return base is not None and base >= MIN_MEANINGFUL_MB


def _kv_inclusion_match(high: NodeProfile, low: NodeProfile) -> Optional[float]:
    """Return the relative error if ``high`` looks like ``low`` plus its KV budget.

    Both sides are expressed as totals across ranks first, so the identity holds
    even when the two nodes shard the model differently.

    ``None`` when the identity does not hold, when the KV budget is unknown, or
    when it is too small to explain the gap.
    """
    kv = _total_kv_mb(high)
    if kv <= 0:
        return None

    high_base = _total_base_mb(high)
    low_base = _total_base_mb(low)
    if high_base <= 0 or low_base <= 0:
        return None

    implied = high_base - kv
    if implied <= 0:
        return None
    return abs(implied - low_base) / low_base


def reconcile_model(profiles: Iterable[NodeProfile]) -> List[Inconsistency]:
    """Compare every node's declaration for a single model."""
    profiles = list(profiles)
    if len(profiles) < 2:
        return []

    model_name = profiles[0].model_name
    findings: List[Inconsistency] = []

    measured = [p for p in profiles if p.is_measured and _usable(p)]

    # Flag a knowledge base resting mostly on defaults.  The check is on the
    # *share* of unmeasured profiles, not on their total absence: a model
    # measured on one node out of three is still being placed on two nodes
    # using figures nobody measured.
    unmeasured = [p for p in profiles if not p.is_measured]
    if len(unmeasured) * 2 > len(profiles):
        findings.append(
            Inconsistency(
                model_name=model_name,
                kind="uncalibrated_majority",
                severity="low",
                detail=(
                    f"{len(unmeasured)} of {len(profiles)} nodes hosting {model_name} have never "
                    "measured it; placement decisions on those nodes rest on defaults"
                ),
                provider_ids=sorted(p.provider_id for p in unmeasured),
                evidence={
                    "hosting_nodes": len(profiles),
                    "measured_nodes": len(profiles) - len(unmeasured),
                    "unmeasured_nodes": len(unmeasured),
                },
            )
        )

    if len(measured) < 2:
        return findings

    ordered = sorted(measured, key=lambda p: _total_base_mb(p))

    # Examine every ordered pair whose residency ratio is too large to explain,
    # not only the extremes.  With three nodes at 10, 20 and 40 GB the
    # KV-inclusion signature may sit in the middle pair, and comparing only
    # min against max would miss it and report the weaker finding instead.
    best_match = None
    for i, low in enumerate(ordered):
        low_mb = _total_base_mb(low)
        if low_mb <= 0:
            continue
        for high in ordered[i + 1 :]:
            high_mb = _total_base_mb(high)
            if high_mb / low_mb <= DISAGREEMENT_RATIO:
                continue
            relative_error = _kv_inclusion_match(high, low)
            if relative_error is None or relative_error > KV_INCLUSION_TOLERANCE:
                continue
            if best_match is None or relative_error < best_match[0]:
                best_match = (relative_error, low, high, high_mb / low_mb)

    if best_match is not None:
        relative_error, low, high, ratio = best_match
        low_mb, high_mb = _total_base_mb(low), _total_base_mb(high)
        kv_mb = _total_kv_mb(high)
        findings.append(
            Inconsistency(
                model_name=model_name,
                kind="kv_inclusion_skew",
                severity="high",
                detail=(
                    f"provider {high.provider_id} reports {high_mb:.0f} MB base residency for "
                    f"{model_name} while provider {low.provider_id} reports {low_mb:.0f} MB "
                    f"(both totals across ranks); the difference matches provider "
                    f"{high.provider_id}'s KV budget ({kv_mb:.0f} MB across {_tp(high)} rank(s)), "
                    "so one build includes "
                    "the KV cache in the residency figure and the other does not"
                ),
                provider_ids=[low.provider_id, high.provider_id],
                evidence={
                    "high_provider": high.provider_id,
                    "high_base_mb": high_mb,
                    "high_kv_budget_mb": kv_mb,
                    "high_tp": high.tensor_parallel_size,
                    "low_provider": low.provider_id,
                    "low_base_mb": low_mb,
                    "low_tp": low.tensor_parallel_size,
                    "implied_after_removing_kv_mb": high_mb - kv_mb,
                    "relative_error": relative_error,
                    "ratio": ratio,
                    "compared_in_total_units": True,
                },
            )
        )
        return findings

    lowest, highest = ordered[0], ordered[-1]
    low_mb = _total_base_mb(lowest)
    high_mb = _total_base_mb(highest)
    if low_mb <= 0:
        return findings
    ratio = high_mb / low_mb
    if ratio <= DISAGREEMENT_RATIO:
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


def is_current(
    profile: NodeProfile,
    *,
    now: Optional[datetime.datetime] = None,
    max_age_days: float = DEFAULT_MAX_PROFILE_AGE_DAYS,
    active_provider_ids: Optional[Set[int]] = None,
) -> bool:
    """Whether this row still describes a node the federation is using.

    Two independent tests, because either alone leaves a gap.  A caller that
    knows which providers are connected passes ``active_provider_ids`` and gets
    an exact answer; otherwise the row's own freshness stands in, since a worker
    that is still attached refreshes its profiles over the status channel.
    """
    if active_provider_ids is not None and profile.provider_id not in active_provider_ids:
        return False
    if profile.updated_at is None:
        # No timestamp: fall back to trusting it, rather than silently
        # discarding rows on databases that predate the column.
        return True
    reference = now or datetime.datetime.now(datetime.timezone.utc)
    updated = profile.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=datetime.timezone.utc)
    return (reference - updated).total_seconds() <= max_age_days * 86_400.0


def reconcile(
    profiles: Iterable[NodeProfile],
    *,
    now: Optional[datetime.datetime] = None,
    max_age_days: float = DEFAULT_MAX_PROFILE_AGE_DAYS,
    active_provider_ids: Optional[Set[int]] = None,
) -> List[Inconsistency]:
    """Group current declarations by model and reconcile each group.

    Historical rows are filtered out first: a disagreement between a live node
    and one that left the federation months ago is not an operational signal,
    and reporting it every ten minutes forever is worse than not reporting it.
    """
    by_model: Dict[str, List[NodeProfile]] = {}
    for profile in profiles:
        if not is_current(profile, now=now, max_age_days=max_age_days, active_provider_ids=active_provider_ids):
            continue
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
                    updated_at=data.get("updated_at"),
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
