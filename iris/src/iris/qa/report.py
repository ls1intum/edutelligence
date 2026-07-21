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


def summarize(evaluations: list[ScenarioEvaluation]) -> dict:
    scenario_means = _scenario_means(evaluations)
    models = sorted({evaluation.model for evaluation in evaluations})
    by_model = {}
    for model in models:
        selected = [
            evaluation for evaluation in evaluations if evaluation.model == model
        ]
        scores = [
            score
            for (score_model, _), score in scenario_means.items()
            if score_model == model
        ]
        critical_trials = sum(item.critical_error_count > 0 for item in selected)
        by_model[model] = {
            **_score_summary(scores),
            "scenarios": len(scores),
            "trials": len(selected),
            "criticalErrorRate": round(
                critical_trials / len(selected) if selected else 0.0, 4
            ),
            "executionErrors": sum(bool(item.execution_error) for item in selected),
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
        "IrisScore is the equal-weight average of the scenario criteria. Each criterion is rated "
        "`achieved` (100), `partly achieved` (50), or `not achieved` (0). Critical errors and "
        "execution errors are reported separately; there is no pass/fail threshold.",
        "",
        "## Results",
        "",
        "| Model | IrisScore | 95% interval | Scenarios | Critical-error rate | Execution errors | Cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, item in summary["models"].items():
        lines.append(
            f"| `{_cell(model)}` | **{item['score']:.2f}** | "
            f"{item['ci95Low']:.2f}–{item['ci95High']:.2f} | {item['scenarios']} | "
            f"{item['criticalErrorRate']:.1%} | {item['executionErrors']} | "
            f"${item['costUsd']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Total measured model cost: **${summary['totalCostUsd']:.4f}**.",
            "",
            "The interval describes variation across this scenario set after averaging repeated "
            "runs of the same scenario. With one repetition it does not measure run-to-run "
            "stability; use `--repetitions 3` or more for that.",
        ]
    )
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
                    lines.append(
                        f"- Critical error: {_cell(error.description)} — {_cell(error.evidence)}"
                    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
