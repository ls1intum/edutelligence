from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from iris.qa.evaluate import ScenarioEvaluation
from iris.qa.rubric import CHAT_MODE_USAGE_WEIGHTS, SHARED_CRITERION_IDS

# pylint: disable=inconsistent-quotes


def _scenario_means(
    evaluations: list[ScenarioEvaluation],
) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for evaluation in evaluations:
        grouped[(evaluation.model, evaluation.scenario_id)].append(evaluation.score)
    return {key: statistics.mean(values) for key, values in grouped.items()}


def _score_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"score": 0.0, "ci95Low": 0.0, "ci95High": 0.0}
    mean = statistics.mean(values)
    if len(values) < 2:
        margin = 0.0
    else:
        margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return {
        "score": round(mean, 2),
        "ci95Low": round(max(0.0, mean - margin), 2),
        "ci95High": round(min(100.0, mean + margin), 2),
    }


def _usage_weighted_score(selected: list[ScenarioEvaluation]) -> float | None:
    """Mean of the chat-mode means, weighted by how much each mode is used."""
    per_scenario: dict[tuple[str, str], list[float]] = defaultdict(list)
    for evaluation in selected:
        if evaluation.use_case == "chat" and evaluation.mode in CHAT_MODE_USAGE_WEIGHTS:
            per_scenario[(evaluation.mode, evaluation.scenario_id)].append(
                evaluation.score
            )
    by_mode: dict[str, list[float]] = defaultdict(list)
    for (mode, _), values in per_scenario.items():
        by_mode[mode].append(statistics.mean(values))
    if not by_mode:
        return None
    total_weight = sum(CHAT_MODE_USAGE_WEIGHTS[mode] for mode in by_mode)
    return round(
        sum(
            CHAT_MODE_USAGE_WEIGHTS[mode] * statistics.mean(values)
            for mode, values in by_mode.items()
        )
        / total_weight,
        2,
    )


def _criterion_scores(selected: list[ScenarioEvaluation]) -> dict[str, float]:
    """Mean points per shared rubric criterion over the answered chat trials."""
    points: dict[str, list[float]] = defaultdict(list)
    for evaluation in selected:
        if evaluation.use_case != "chat" or evaluation.execution_error:
            continue
        for item in evaluation.criteria:
            if item.id in SHARED_CRITERION_IDS:
                points[item.id].append(item.points)
    return {
        criterion: round(statistics.mean(points[criterion]), 2)
        for criterion in SHARED_CRITERION_IDS
        if points.get(criterion)
    }


def summarize(evaluations: list[ScenarioEvaluation]) -> dict:
    scenario_means = _scenario_means(evaluations)
    models = sorted({evaluation.model for evaluation in evaluations})
    by_model = {}
    for model in models:
        selected = [
            evaluation for evaluation in evaluations if evaluation.model == model
        ]
        repeated: dict[str, list[float]] = defaultdict(list)
        for evaluation in selected:
            repeated[evaluation.scenario_id].append(evaluation.score)
        repeat_spans = [
            max(values) - min(values) for values in repeated.values() if len(values) > 1
        ]
        scores = [
            score
            for (score_model, _), score in scenario_means.items()
            if score_model == model
        ]
        critical_trials = sum(item.critical_error_count > 0 for item in selected)
        chat_usable = [item.usable for item in selected if item.usable is not None]
        by_model[model] = {
            **_score_summary(scores),
            "usableShare": (
                round(sum(chat_usable) / len(chat_usable), 4) if chat_usable else None
            ),
            "usageWeightedScore": _usage_weighted_score(selected),
            "criterionScores": _criterion_scores(selected),
            "scenarios": len(scores),
            "trials": len(selected),
            "criticalErrorRate": round(
                critical_trials / len(selected) if selected else 0.0, 4
            ),
            "executionErrors": sum(bool(item.execution_error) for item in selected),
            "repeatedScenarios": len(repeat_spans),
            "meanRepeatSpan": (
                round(statistics.mean(repeat_spans), 2) if repeat_spans else None
            ),
            "maxRepeatSpan": round(max(repeat_spans), 2) if repeat_spans else None,
            "costUsd": round(sum(item.cost_usd for item in selected), 4),
            "meanDurationSeconds": round(
                (
                    statistics.mean(item.duration_seconds for item in selected)
                    if selected
                    else 0.0
                ),
                2,
            ),
        }
    return {
        "models": by_model,
        "totalTrials": len(evaluations),
        "totalCostUsd": round(sum(item.cost_usd for item in evaluations), 4),
        "executionErrors": sum(bool(item.execution_error) for item in evaluations),
    }


def _breakdown(
    evaluations: list[ScenarioEvaluation],
    key: Callable[[ScenarioEvaluation], str],
) -> list[dict]:
    scenario_scores = _scenario_means(evaluations)
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for evaluation in evaluations:
        identity = (evaluation.model, evaluation.scenario_id, key(evaluation))
        if identity in seen:
            continue
        seen.add(identity)
        grouped[(evaluation.model, identity[2])].append(
            scenario_scores[(evaluation.model, evaluation.scenario_id)]
        )
    return [
        {
            "model": model,
            "group": group,
            "scenarios": len(values),
            **_score_summary(values),
        }
        for (model, group), values in sorted(grouped.items())
    ]


def report_payload(
    evaluations: list[ScenarioEvaluation], *, metadata: dict | None = None
) -> dict:
    public_evaluations = []
    for evaluation in evaluations:
        item = asdict(evaluation)
        item.pop("response", None)
        item["score"] = round(evaluation.score, 2)
        item["critical_error_count"] = evaluation.critical_error_count
        item["usable"] = evaluation.usable
        public_evaluations.append(item)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "summary": summarize(evaluations),
        "breakdowns": {
            "useCase": _breakdown(evaluations, lambda item: item.use_case),
            "chatMode": _breakdown(
                evaluations, lambda item: item.mode or "not_applicable"
            ),
            "supportLevel": _breakdown(
                evaluations, lambda item: item.support_level or "not_applicable"
            ),
            "difficulty": _breakdown(evaluations, lambda item: item.difficulty),
        },
        "evaluations": public_evaluations,
    }


def write_json_report(
    path: Path,
    evaluations: list[ScenarioEvaluation],
    *,
    metadata: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report_payload(evaluations, metadata=metadata),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_markdown_report(
    path: Path,
    evaluations: list[ScenarioEvaluation],
    *,
    metadata: dict | None = None,
) -> None:
    payload = report_payload(evaluations, metadata=metadata)
    summary = payload["summary"]
    lines = [
        "# Iris Benchmark Report",
        "",
        (
            "IrisScore is the equal-weight average of the scenario criteria. Each "
            "criterion is rated `achieved` (100), `partly achieved` (50), or "
            "`not achieved` (0). Chat scenarios are rated on the five shared rubric "
            "criteria described in `qa/RUBRIC.md`. Critical errors and execution "
            "errors are reported separately; there is no pass/fail threshold."
        ),
        "",
        (
            "**Usable answers** is the share of chat answers a student could rely "
            "on: no critical error, and neither trustworthy nor moves-forward rated "
            "`not achieved`. **Usage-weighted** applies the usage share of each chat "
            "mode to the chat-mode means so a rarely used mode cannot move the "
            "headline."
        ),
        "",
        "## Results",
        "",
        "| Model | IrisScore | Usable answers | Usage-weighted | 95% interval | "
        "Scenarios | Mean/max repeat span | Critical-error rate | Execution errors | "
        "Cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, item in summary["models"].items():
        repeat_span = (
            f"{item['meanRepeatSpan']:.2f} / {item['maxRepeatSpan']:.2f}"
            if item["meanRepeatSpan"] is not None
            else "—"
        )
        usable = (
            f"{item['usableShare']:.1%}" if item["usableShare"] is not None else "—"
        )
        weighted = (
            f"{item['usageWeightedScore']:.2f}"
            if item["usageWeightedScore"] is not None
            else "—"
        )
        lines.append(
            f"| `{_cell(model)}` | **{item['score']:.2f}** | {usable} | {weighted} | "
            f"{item['ci95Low']:.2f}–{item['ci95High']:.2f} | {item['scenarios']} | "
            f"{repeat_span} | "
            f"{item['criticalErrorRate']:.1%} | {item['executionErrors']} | "
            f"${item['costUsd']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Total measured model cost: **${summary['totalCostUsd']:.4f}**.",
            "",
            (
                "The interval describes variation across this scenario set after "
                "averaging repeated runs of the same scenario. With one repetition it "
                "does not measure run-to-run stability; use `--repetitions 3` or more "
                "for that."
            ),
        ]
    )
    criterion_rows = [
        (model, item["criterionScores"])
        for model, item in summary["models"].items()
        if item["criterionScores"]
    ]
    if criterion_rows:
        lines.extend(
            [
                "",
                "## By rubric criterion (chat scenarios, mean points)",
                "",
                "| Model | "
                + " | ".join(f"`{c}`" for c in SHARED_CRITERION_IDS)
                + " |",
                "| --- | " + " | ".join("---:" for _ in SHARED_CRITERION_IDS) + " |",
            ]
        )
        for model, scores in criterion_rows:
            cells = [
                f"{scores[c]:.1f}" if c in scores else "—" for c in SHARED_CRITERION_IDS
            ]
            lines.append(f"| `{_cell(model)}` | " + " | ".join(cells) + " |")
    for label, rows in payload["breakdowns"].items():
        lines.extend(
            [
                "",
                f"## By {label}",
                "",
                "| Model | Group | IrisScore | Scenarios |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for row in rows:
            lines.append(
                f"| `{_cell(row['model'])}` | `{_cell(row['group'])}` | "
                f"{row['score']:.2f} | {row['scenarios']} |"
            )
    lines.extend(
        [
            "",
            "## Scenarios",
            "",
            "| Scenario | Model | Run | IrisScore | Critical errors |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for evaluation in evaluations:
        lines.append(
            f"| `{_cell(evaluation.scenario_id)}` | `{_cell(evaluation.model)}` | "
            f"{evaluation.repetition} | {evaluation.score:.2f} | "
            f"{evaluation.critical_error_count} |"
        )
    incidents = [
        evaluation
        for evaluation in evaluations
        if evaluation.execution_error or evaluation.critical_error_count
    ]
    if incidents:
        lines.extend(["", "## Incidents", ""])
        for evaluation in incidents:
            lines.append(
                f"### {_cell(evaluation.scenario_id)} / {_cell(evaluation.model)} / "
                f"run {evaluation.repetition}"
            )
            lines.append("")
            if evaluation.execution_error:
                lines.append(f"- Execution error: {_cell(evaluation.execution_error)}")
            for error in evaluation.critical_errors:
                if error.present:
                    description = _cell(error.description)
                    evidence = _cell(error.evidence)
                    lines.append(f"- Critical error: {description} — {evidence}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
