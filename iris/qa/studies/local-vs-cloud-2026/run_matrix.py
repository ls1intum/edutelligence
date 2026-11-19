"""Run every situation x configuration x repetition, resumable, with a spend stop.

Usage: run_matrix.py OUT_NAME REPS LABELS...   e.g. run_matrix.py runs 2 C1 C3 L1
Results go to $IRIS_STUDY_DATA/OUT_NAME/LABEL/<situation>__r<rep>.json.
Configurations run side by side; each has its own number of parallel requests.
"""

import json
import os
import subprocess  # nosec B404 - runs this study's own run_one.py
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from study_paths import DATA, IRIS, SCENARIOS, STUDY, config_dir

# label: (config file, selection, variant, parallel requests, spend group)
CONFIGS = {
    "C1": (
        "base",
        "CLOUD_AI",
        "default",
        8,
        "openai",
    ),  # GPT-6 Luna (production default)
    "C2": (
        "base",
        "CLOUD_AI",
        "advanced",
        8,
        "openai",
    ),  # GPT-6.1 Sol (production advanced)
    "C3": ("terra", "CLOUD_AI", "default", 8, "openai"),  # GPT-6.1 Terra, medium
    "L1": ("base", "LOCAL_AI", "default", 8, None),  # Qwen3.8-27B (production local)
    "L2": ("gptoss", "LOCAL_AI", "default", 6, None),  # gpt-oss-120b
    "L3": ("gemma", "LOCAL_AI", "default", 6, None),  # Gemma 4 31B, thinking off
    "L4": ("gemmathink", "LOCAL_AI", "default", 8, None),  # Gemma 4 31B, thinking on
    "A1": ("opus", "CLOUD_AI", "default", 6, "anthropic"),
    "A2": ("sonnet", "CLOUD_AI", "default", 6, "anthropic"),
}
# Estimated USD per spend group from the stored usage (production price rows,
# without prompt-cache discounts). Check the provider's own records as well.
STOP = {"openai": 18.0, "anthropic": 18.0}
INFRA = ("402", "429", "500", "502", "503", "504", "Timeout", "timed out", "Connection")
LOCK = threading.Lock()


def spend(out: Path) -> dict[str, float]:
    total = {"openai": 0.0, "anthropic": 0.0}
    for path in out.rglob("*.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for usage in result.get("usage", []):
            group = "anthropic" if "claude" in usage["model"] else "openai"
            total[group] += usage["costUsd"]
    return total


def run_one(
    config: str, scenario: Path, label: str, selection: str, variant: str, target: Path
) -> None:
    """Run one situation in its own process with the configuration's settings."""
    cfg = config_dir()
    env = {
        **os.environ,
        "APPLICATION_YML_PATH": str(cfg / f"application.{config}.yml"),
        "LLM_CONFIG_PATH": str(cfg / "llm_config.yml"),
    }
    command = [
        sys.executable,
        str(STUDY / "run_one.py"),
        str(scenario),
        label,
        selection,
        variant,
        str(target),
    ]
    try:
        subprocess.run(  # nosec B603 - fixed command, no shell
            command,
            cwd=IRIS,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pass


def trial(scenario: Path, label: str, rep: int, out: Path) -> None:
    config, selection, variant, _, group = CONFIGS[label]
    target = out / label / f"{scenario.stem}__r{rep}.json"
    if (
        target.exists()
        and json.loads(target.read_text(encoding="utf-8")).get("executionError") is None
    ):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        if group:
            with LOCK:
                if spend(out)[group] >= STOP[group]:
                    print(
                        f"STOP {group} budget reached, skip {label} {scenario.stem}",
                        flush=True,
                    )
                    return
        run_one(config, scenario, label, selection, variant, target)
        error = (
            json.loads(target.read_text(encoding="utf-8")).get("executionError")
            if target.exists()
            else "no result (killed or timed out)"
        )
        if error is None:
            print(f"ok {label} {scenario.stem} r{rep}", flush=True)
            return
        infra = any(marker in error for marker in INFRA) or error.startswith(
            "no result"
        )
        print(
            f"ERR {label} {scenario.stem} r{rep} a{attempt} infra={infra}: {error[:160]}",
            flush=True,
        )
        if not infra:
            return  # a product failure is a finding; keep it and do not retry
        time.sleep(20)


def main() -> None:
    out, reps, labels = DATA / sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    scenarios = sorted(
        path for path in SCENARIOS.glob("*.json") if path.name != "manifest.json"
    )
    pools = {label: ThreadPoolExecutor(CONFIGS[label][3]) for label in labels}
    futures = [
        pools[label].submit(trial, scenario, label, rep, out)
        for rep in range(1, reps + 1)
        for scenario in scenarios
        for label in labels
    ]
    for future in futures:
        future.result()
    print("DONE", json.dumps(spend(out)), flush=True)


if __name__ == "__main__":
    main()
