"""Blind point judging of stored runs with Claude Opus through the Claude Code CLI.

Usage: judge_points.py OUT_NAME --select SPEC [--workers N]
SPEC: comma list of RUNDIR:LABEL:REPS, e.g. runs:C1:1+2,runs:L1:1+2
Writes $IRIS_STUDY_DATA/judge/OUT_NAME.jsonl, resumable by bundle id.

Uses the shared rubric and judge prompt of iris.qa.worker. The judge sees only the
stored judge input (no configuration, no model name). `claude -p` runs on a Claude
subscription; its 5-hour limit stops long runs, which then resume where they stopped.
"""

import argparse
import ast
import hashlib
import json
import random
import re
import subprocess  # nosec B404 - calls the local Claude Code CLI
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from study_paths import DATA, IRIS

# Salt for the opaque bundle ids; changing it changes every id.
SALT = "local-vs-cloud-2026"
SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "rating": {
                        "type": "string",
                        "enum": ["achieved", "partly_achieved", "not_achieved"],
                    },
                    "evidence": {"type": "string"},
                },
                "required": ["id", "rating", "evidence"],
            },
        },
        "criticalErrors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "present": {"type": "boolean"},
                    "evidence": {"type": "string"},
                },
                "required": ["description", "present", "evidence"],
            },
        },
    },
    "required": ["criteria", "criticalErrors"],
}
LOCK = threading.Lock()


def judge_prompt() -> str:
    """The harness judge prompt, read from the worker source.

    Importing iris.qa.worker would load the Iris settings, which judging does
    not need.
    """
    tree = ast.parse(
        (IRIS / "src" / "iris" / "qa" / "worker.py").read_text(encoding="utf-8")
    )
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "JUDGE_SYSTEM_PROMPT"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("JUDGE_SYSTEM_PROMPT not found in iris/qa/worker.py")


def bundles(spec: str) -> list[dict]:
    out = []
    for item in spec.split(","):
        rundir, label, reps = item.split(":")
        wanted = {int(rep) for rep in reps.split("+")}
        for path in sorted((DATA / rundir / label).glob("*.json")):
            match = re.search(r"__r(\d+)", path.name)
            if not match or int(match.group(1)) not in wanted:
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("executionError") or "judgeInput" not in result:
                continue
            bundle_id = hashlib.sha256(f"{SALT}:{path}".encode()).hexdigest()[:16]
            out.append(
                {"id": bundle_id, "path": str(path), "input": result["judgeInput"]}
            )
    random.Random(7).shuffle(out)  # nosec B311 - judging order, not security
    return out


def run_opus(system: str, user: str) -> dict:
    workdir = Path(tempfile.gettempdir()) / "iris-study-judge-cwd"
    workdir.mkdir(exist_ok=True)
    command = [
        "claude", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--tools", "",
        "--system-prompt", system, "--setting-sources", "", "--strict-mcp-config",
        "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
    ]  # fmt: skip
    done = subprocess.run(  # nosec B603 B607 - fixed command, no shell
        command,
        input=user,
        capture_output=True,
        text=True,
        cwd=workdir,
        timeout=900,
        check=False,
    )
    data = json.loads(done.stdout)
    if data.get("is_error"):
        detail = str(data.get("result"))[:200]
        raise ValueError(f"claude error: {detail}")
    models = list(data.get("modelUsage", {}))
    if models != ["claude-opus-5-5"]:
        raise ValueError(f"unexpected models {models}")
    payload = data.get("structured_output")
    text = json.dumps(payload) if payload else data.get("result", "")
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_name")
    parser.add_argument("--select", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    out = DATA / "judge" / f"{args.out_name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {json.loads(line)["id"] for line in out.open(encoding="utf-8")}
        if out.exists()
        else set()
    )
    todo = [bundle for bundle in bundles(args.select) if bundle["id"] not in done]
    system = judge_prompt()
    print(f"{len(done)} done, {len(todo)} to do", flush=True)

    def work(bundle: dict) -> None:
        expected = [criterion["id"] for criterion in bundle["input"]["criteria"]]
        user = json.dumps(bundle["input"], ensure_ascii=False, default=str)
        last = None
        for attempt in range(3):
            try:
                data = run_opus(system, user)
                ratings = {item["id"]: item["rating"] for item in data["criteria"]}
                missing = [
                    criterion for criterion in expected if criterion not in ratings
                ]
                if missing:
                    raise ValueError(f"missing criteria {missing}")
                row = {
                    "id": bundle["id"],
                    "path": bundle["path"],
                    "judge": "opus",
                    "ratings": ratings,
                    "criticalErrors": data.get("criticalErrors", []),
                    "result": data,
                }
                with LOCK, out.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                print("ok", bundle["id"], flush=True)
                return
            except Exception as error:  # pylint: disable=broad-exception-caught
                last = f"{type(error).__name__}: {str(error)[:300]}"
                time.sleep(10 * (attempt + 1))
        print("FAIL", bundle["id"], last, flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, todo))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
