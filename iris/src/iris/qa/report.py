from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree  # nosec B405 - generation only, never parses input

from iris.qa.evaluate import ScenarioEvaluation

# pylint: disable=inconsistent-quotes


_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|api)-[A-Za-z0-9_-]{10,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|authentication[_ -]?token|"
        r"authorization|password|secret(?:[_ -]?(?:key|token))?)\b"
        r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        re.IGNORECASE,
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\." r"[A-Za-z0-9_-]{8,}\b"),
)


def _sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def _sanitize_value(value):
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _publishable_evaluation(evaluation: ScenarioEvaluation) -> dict:
    payload = asdict(evaluation)
    # Raw answers and tool payloads stay in qa-results/<run>/raw for local
    # diagnosis. The weekly workflow deliberately never uploads that directory.
    payload.pop("response", None)
    payload["activities"] = [
        {"name": activity.name, "state": activity.state}
        for activity in evaluation.activities
    ]
    return _sanitize_value(payload)


def _markdown_cell(value: str) -> str:
    return _sanitize_text(value).replace("|", "\\|").replace("\n", " ")


def _xml_text(value: str) -> str:
    # XML 1.0 rejects most C0 controls even after ElementTree escaping.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", _sanitize_text(value))


def write_json_report(
    path: Path,
    evaluations: list[ScenarioEvaluation],
    *,
    metadata: dict | None = None,
) -> None:
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "summary": _summary(evaluations),
        "evaluations": [
            _publishable_evaluation(evaluation) for evaluation in evaluations
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )


def write_markdown_report(
    path: Path,
    evaluations: list[ScenarioEvaluation],
    *,
    metadata: dict | None = None,
) -> None:
    summary = _summary(evaluations)
    metadata = metadata or {}
    gates = metadata.get("gates", {})
    lines = [
        "# Iris QA Report",
        "",
        f"- Scenarios: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Critical failures: {summary['criticalFailures']}",
        f"- Mean score: {summary['meanScore']:.3f}",
    ]
    accounted_spend = metadata.get("accountedSpendUsd", metadata.get("actualSpendUsd"))
    if accounted_spend is not None:
        lines.extend(
            [
                f"- Accounted run spend: ${metadata.get('runSpendUsd', '?')} / "
                f"${metadata.get('runMaxCostUsd', '?')}",
                "- Measured run usage: "
                f"${metadata.get('measuredRunSpendUsd', metadata.get('runSpendUsd', '?'))}",
                f"- Pessimistic plan: ${metadata.get('plannedCostUsd', '?')}",
                "- Global transient retries: "
                f"{metadata.get('transientRetriesUsed', 0)} used / "
                f"{metadata.get('transientRetriesConfigured', 0)} configured "
                f"(${metadata.get('transientRetryAllowanceUsd', '0')} planned "
                "allowance)",
                f"- Worker attempts: {metadata.get('workerAttemptCount', '?')}",
                f"- Accounted cumulative upper bound: ${accounted_spend} / "
                f"${metadata.get('developmentHardLimitUsd', '?')}",
                "- Measured cumulative usage: "
                f"${metadata.get('measuredUsageSpendUsd', accounted_spend)}",
                f"- Rate source: {metadata.get('rateSource', '?')}",
            ]
        )
        if Decimal(str(metadata.get("ambiguousReserveUsd", "0"))) > 0:
            lines.append(
                "- Ambiguous-call reserve included above: "
                f"${metadata['ambiguousReserveUsd']} (conservative upper bound)"
            )
    if gates:
        regressions = gates.get("regressions", [])
        lines.extend(
            [
                f"- Aggregate pass rate: {gates.get('passRate', 0):.1%}",
                f"- Critical groups passed: "
                f"{'yes' if gates.get('criticalPassRate') == 1.0 else 'no'}",
                f"- Regressions: {len(regressions)}",
            ]
        )
    composite_run_ids = metadata.get("compositeRunIds", [])
    if composite_run_ids:
        lines.extend(
            [
                "",
                "## Composite qualification provenance",
                "",
                "- Evaluations are the fail-closed union of disjoint "
                "scenario/model/repetition observations from the contributing runs.",
                "- Spend and provider usage include every call and reservation in "
                "the contributing runs.",
                "- Contributing run IDs: "
                + ", ".join(
                    f"`{_markdown_cell(str(run_id))}`" for run_id in composite_run_ids
                ),
            ]
        )
    deployments = metadata.get("azureDeployments", {})
    if deployments:
        lines.extend(
            [
                "",
                "## Verified Azure models",
                "",
                "| QA role | Deployment | Model version |",
                "| --- | --- | --- |",
            ]
        )
        for model, item in sorted(deployments.items()):
            lines.append(
                f"| `{_markdown_cell(model)}` | "
                f"`{_markdown_cell(str(item['deployment']))}` | "
                f"`{_markdown_cell(str(item['version']))}` |"
            )
    if metadata.get("corpusSha256") and metadata.get("irisSourceSha256"):
        lines.extend(
            [
                "",
                "## Reproducibility",
                "",
                f"- Selected corpus SHA-256: `{metadata['corpusSha256']}`",
                f"- Iris source and prompts SHA-256: "
                f"`{metadata['irisSourceSha256']}`",
            ]
        )
    usage = metadata.get("providerUsage", {})
    if usage:
        lines.extend(
            [
                "",
                "## Provider usage",
                "",
                "| Model | Calls | Input | Output | Max input/call | "
                "Max output/call | Cost |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for model, item in sorted(usage.items()):
            lines.append(
                f"| `{_markdown_cell(model)}` | {item['calls']} | "
                f"{item['inputTokens']} | {item['outputTokens']} | "
                f"{item['maxInputTokensPerCall']} | "
                f"{item['maxOutputTokensPerCall']} | ${item['costUsd']} |"
            )
    lines.extend(
        [
            "",
            "| Scenario | Model | Score | Result |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for evaluation in evaluations:
        status = "PASS" if evaluation.passed else "FAIL"
        lines.append(
            f"| `{_markdown_cell(evaluation.scenario_id)}` | "
            f"`{_markdown_cell(evaluation.model)}` | "
            f"{evaluation.score:.3f} | {status} |"
        )
    regressions = gates.get("regressions", [])
    if regressions:
        lines.extend(
            [
                "",
                "## Regressions",
                "",
                "| Scenario / model | Dimension | Baseline | Current | Drop | Sigma |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for regression in regressions:
            sigma = regression["sigma_drop"]
            sigma_display = "infinite" if sigma is None else f"{float(sigma):.2f}"
            lines.append(
                f"| `{_markdown_cell(str(regression['key']))}` | "
                f"`{_markdown_cell(str(regression['dimension']))}` | "
                f"{float(regression['baseline_mean']):.3f} | "
                f"{float(regression['current_mean']):.3f} | "
                f"{float(regression['fixed_drop']):.3f} | {sigma_display} |"
            )
    failures = [evaluation for evaluation in evaluations if not evaluation.passed]
    if failures:
        lines.extend(["", "## Failures", ""])
        for evaluation in failures:
            lines.append(f"### {evaluation.scenario_id} / {evaluation.model}")
            lines.append("")
            if evaluation.execution_error:
                lines.append(
                    f"Execution error: {_markdown_cell(evaluation.execution_error)}"
                )
            for check in evaluation.checks:
                if not check.passed:
                    severity = "critical" if check.critical else "quality"
                    lines.append(
                        f"- `{severity}` `{_markdown_cell(check.id)}`: "
                        f"{_markdown_cell(check.message)}"
                    )
            for criterion, score in sorted(evaluation.semantic_scores.items()):
                evidence = evaluation.semantic_evidence.get(criterion, "")
                lines.append(
                    f"- `judge` `{_markdown_cell(criterion)}`: {score:.2f} — "
                    f"{_markdown_cell(evidence)}"
                )
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_junit_report(path: Path, evaluations: list[ScenarioEvaluation]) -> None:
    summary = _summary(evaluations)
    errors = sum(bool(item.execution_error) for item in evaluations)
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "iris-qa",
            "tests": str(summary["total"]),
            "failures": str(summary["failed"] - errors),
            "errors": str(errors),
        },
    )
    for evaluation in evaluations:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "classname": f"iris.qa.{evaluation.model}",
                "name": evaluation.scenario_id,
            },
        )
        if evaluation.execution_error:
            error = ElementTree.SubElement(
                case,
                "error",
                {"message": _xml_text(evaluation.execution_error)},
            )
            error.text = _xml_text(evaluation.execution_error)
        elif not evaluation.passed:
            failure = ElementTree.SubElement(
                case,
                "failure",
                {"message": "Quality threshold failed"},
            )
            details = [check.message for check in evaluation.checks if not check.passed]
            details.extend(
                f"{criterion}={score:.2f}: "
                f"{evaluation.semantic_evidence.get(criterion, '')}"
                for criterion, score in sorted(evaluation.semantic_scores.items())
            )
            failure.text = _xml_text("\n".join(details))
    tree = ElementTree.ElementTree(suite)
    ElementTree.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _summary(evaluations: list[ScenarioEvaluation]) -> dict:
    total = len(evaluations)
    passed = sum(evaluation.passed for evaluation in evaluations)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "criticalFailures": sum(
            evaluation.critical_failure for evaluation in evaluations
        ),
        "meanScore": (
            sum(evaluation.score for evaluation in evaluations) / total
            if total
            else 0.0
        ),
    }
