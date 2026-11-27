"""Clean answer-time run: one request at a time per configuration.

Usage: run_latency.py OUT_NAME LABELS...   e.g. run_latency.py timing C1 C3 L1 L4

Configurations run side by side (each model has its own backend), so no model ever
sees more than one concurrent request from this study. Never run it while a quality
run is active. The first request per configuration (index 00) is a warm-up and is
not reported. Cloud models and gpt-oss get 10 situations, Qwen and Gemma 25.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from run_matrix import CONFIGS, run_one
from study_paths import DATA, SCENARIOS

# Fixed before any timing was seen: 8 programming, 1 course, 1 lecture (production mix).
SITUATIONS = [
    "common-maze-stuck-low",
    "common-sort-start-moderate",
    "common-compile-semicolon-low-de",
    "prog-failed-test-moderate",
    "holdout-prog-sorting-low",
    "common-maze-bfs-dfs-moderate-de",
    "prog-compile-low",
    "common-sort-points-moderate",
    "course-upcoming-deadline-moderate",
    "lecture-slide-low",
]
WARM_UP = "prog-concept-low"
LONG = {"L1", "L3", "L4"}


def extra_situations() -> list[str]:
    ids = sorted(json.loads((SCENARIOS / "manifest.json").read_text(encoding="utf-8")))
    return [sid for sid in ids if sid not in SITUATIONS and sid != WARM_UP][:15]


def stream(label: str, out_name: str) -> None:
    config, selection, variant, *_ = CONFIGS[label]
    order = [WARM_UP] + SITUATIONS + (extra_situations() if label in LONG else [])
    for index, sid in enumerate(order):
        target = DATA / out_name / label / f"{index:02d}-{sid}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        run_one(config, SCENARIOS / f"{sid}.json", label, selection, variant, target)
        print(f"{label} {index} {sid} done", flush=True)


def main() -> None:
    out_name, labels = sys.argv[1], sys.argv[2:]
    with ThreadPoolExecutor(len(labels)) as pool:
        list(pool.map(lambda label: stream(label, out_name), labels))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
