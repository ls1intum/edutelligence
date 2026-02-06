from __future__ import annotations

from collections import defaultdict

from iris.web.routers.health.health_model import ServiceStatus
from iris.web.routers.health.Pipelines.checker import FeatureResult
from iris.web.routers.health.Pipelines.features import CRITICAL_PIPELINES


def derive_status(results: list[FeatureResult]) -> ServiceStatus:
    total = len(results)
    defaults_valid = sum(1 for r in results if r.has_default)
    critical_blockers = any(
        r.feature in CRITICAL_PIPELINES and not r.has_default for r in results
    )
    if critical_blockers:
        return ServiceStatus.DOWN
    if defaults_valid < total:
        return ServiceStatus.DEGRADED
    has_non_default_missing = any(r.missing_models for r in results)
    if has_non_default_missing:
        return ServiceStatus.WARN
    return ServiceStatus.UP


def format_summary(results: list[FeatureResult]) -> str:
    total = len(results)
    defaults_valid = sum(1 for r in results if r.has_default)

    header = f"{defaults_valid}/{total} pipelines have valid LLM configurations"
    lines = [header + ("" if defaults_valid == total else ".")]

    missing_by_model: dict[str, list[str]] = defaultdict(list)
    for r in results:
        for m in r.missing_models:
            missing_by_model[m].append(r.feature.value.lower())

    if missing_by_model:
        lines.append("Missing models/configuration:")
        for model in sorted(missing_by_model):
            feats = ", ".join(sorted(set(missing_by_model[model])))
            lines.append(f"- {model} ({feats})")

    return "\n".join(lines)
