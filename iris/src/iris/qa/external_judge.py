"""Rate collected benchmark answers with a judge that runs outside the harness.

``iris-benchmark run --skip-judge`` stores, for every trial, the exact input the
built-in judge would receive. ``judge-export`` turns those into blinded bundles
with opaque ids, an external judge (for example a Claude session) writes one
judgment per bundle in the same JSON shape the built-in judge returns, and
``judge-import`` validates the judgments and produces the usual report.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from iris.qa.evaluate import ScenarioEvaluation, evaluation_from_worker
from iris.qa.report import write_json_report, write_markdown_report
from iris.qa.run import COLLECTION_FILE

KEY_FILE = "key.json"
BUNDLE_DIRECTORY = "bundles"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {path}: {error}") from error


def _collection(run_root: Path) -> dict:
    collection = _read_json(run_root / COLLECTION_FILE)
    if not isinstance(collection.get("trials"), list):
        raise ValueError(f"{run_root / COLLECTION_FILE} lists no trials")
    return collection


def export_judge_bundles(*, run_root: Path, output_root: Path, seed: int = 1) -> int:
    """Write one blinded judge bundle per answered trial and a key for the ids.

    The bundle file names and ids carry no model or repetition information, and
    the order is shuffled with ``seed`` so neither can hint at which model
    produced an answer. Returns the number of bundles written.
    """
    collection = _collection(run_root)
    answered = [
        trial
        for trial in collection["trials"]
        if not trial.get("executionError") and trial.get("judgePending")
    ]
    failed = [trial for trial in collection["trials"] if trial.get("executionError")]
    random.Random(seed).shuffle(answered)  # nosec B311 - blinding order, not security
    bundles = output_root / BUNDLE_DIRECTORY
    bundles.mkdir(parents=True, exist_ok=False)
    key: dict[str, dict] = {}
    for index, trial in enumerate(answered, start=1):
        bundle_id = f"t{index:03d}"
        stem = trial["stem"]
        raw = _read_json(run_root / "raw" / f"{stem}.output.json")
        judge_input = raw.get("judgeInput")
        if not isinstance(judge_input, dict):
            raise ValueError(f"Trial {stem} has no stored judge input")
        (bundles / f"{bundle_id}.json").write_text(
            json.dumps(
                {
                    "id": bundle_id,
                    "systemPrompt": judge_input["systemPrompt"],
                    "request": judge_input["request"],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        key[bundle_id] = trial
    (output_root / KEY_FILE).write_text(
        json.dumps({"trials": key, "failed": failed}, indent=2), encoding="utf-8"
    )
    return len(answered)


def import_judgments(
    *,
    run_root: Path,
    judgments_root: Path,
    key_path: Path,
    output_root: Path,
    scenarios: dict,
    judge_label: str,
) -> tuple[int, list[ScenarioEvaluation]]:
    """Combine the collected answers with the external judgments into the usual report.

    Every bundle must have a valid judgment (exact criterion ids, valid ratings,
    one result per critical error); a missing or invalid one stops the import with
    the offending ids listed.
    """
    key = _read_json(key_path)
    evaluations: list[ScenarioEvaluation] = []
    problems: list[str] = []
    entries = [(bundle_id, trial) for bundle_id, trial in key["trials"].items()]
    entries += [(None, trial) for trial in key.get("failed", [])]
    for bundle_id, trial in sorted(entries, key=lambda item: item[1]["stem"]):
        scenario_id = trial["scenarioId"]
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            raise ValueError(f"Unknown scenario in key: {scenario_id}")
        stem = trial["stem"]
        payload = _read_json(run_root / "raw" / f"{stem}.output.json")
        payload.pop("judgePending", None)
        if bundle_id is not None:
            judgment_path = judgments_root / f"{bundle_id}.json"
            if not judgment_path.exists():
                problems.append(f"{bundle_id}: no judgment file")
                continue
            payload["judge"] = _read_json(judgment_path)
        try:
            evaluations.append(
                evaluation_from_worker(
                    scenario,
                    model=trial["model"],
                    repetition=int(trial["repetition"]),
                    payload=payload,
                    duration_seconds=float(trial.get("durationSeconds", 0)),
                )
            )
        except ValueError as error:
            problems.append(f"{bundle_id}: {error}")
    if problems:
        raise ValueError(
            f"{len(problems)} judgment(s) are missing or invalid:\n  "
            + "\n  ".join(problems)
        )
    collection = _collection(run_root)
    metadata = {
        **collection.get("metadata", {}),
        "judge": judge_label,
        "judgeRoute": "external, blinded bundles",
    }
    write_json_report(output_root / "report.json", evaluations, metadata=metadata)
    write_markdown_report(output_root / "report.md", evaluations, metadata=metadata)
    return (1 if any(item.execution_error for item in evaluations) else 0), evaluations
