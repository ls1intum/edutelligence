"""Generate resource-mode workloads for ECCS ablation benchmarks.

Creates bursty-with-gaps arrival patterns that force warm→sleeping→warm
transitions between activity windows, making ECCS correction decisions
meaningful. Models go to sleep after ~5s idle, so gaps of 60-70s
guarantee sleeping state at the start of each burst.

The workloads omit the ``model`` field (resource mode), so the
classification layer picks models and ECCS corrects the selection
based on infrastructure state.

Weight scenarios (tight/medium/wide) are controlled at runtime via
``ECCS_WEIGHT_OVERRIDE`` env var — not baked into the workload.

Usage:
    python3 tests/performance/generate_ablation_workloads.py
    # → tests/performance/workloads/ablation/150_burst5_gap70.csv
    # → tests/performance/workloads/ablation/150_burst5_gap30.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path


SEED = 20260412


@dataclass(frozen=True)
class Archetype:
    key: str
    system_tags: str
    followups: tuple[str, ...]
    prompts: tuple[str, ...]
    max_tokens_range: tuple[int, int]
    temperature_range: tuple[float, float]
    interactive_weight: float
    high_priority_weight: float
    mid_priority_weight: float


# Diverse prompts that match different classification profiles.
# No model names — classification + ECCS decide the model.
ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        key="code_quick",
        system_tags="coding code python typescript debugging refactor tests efficient fast",
        followups=(
            "Keep the answer patch-focused and compact.",
            "Bias toward the smallest safe fix.",
        ),
        prompts=(
            "Patch a small {language} handler that breaks when {signal} appears in {place}; keep the change short.",
            "Debug a compact {language} endpoint where {role} reports {issue}; propose a fast fix.",
            "Tighten a tiny {language} parser used by {team}; remove the flaky edge around {signal}.",
            "Fix a flaky {language} validator used in {place}; suggest one focused test.",
        ),
        max_tokens_range=(140, 240),
        temperature_range=(0.05, 0.25),
        interactive_weight=0.85,
        high_priority_weight=0.30,
        mid_priority_weight=0.50,
    ),
    Archetype(
        key="code_deep",
        system_tags="coding code architecture refactor debugging reasoning complex",
        followups=(
            "Prefer architectural tradeoffs and explicit failure analysis.",
            "Bias toward careful debugging across module boundaries.",
        ),
        prompts=(
            "Diagnose a complex {language} scheduling regression across {module_a}, {module_b}, and {module_c}; explain the safest rollout.",
            "Compare two backend designs for a {domain} policy engine after {role} reports {issue}; recommend one.",
            "Review a multi-module refactor in {language}; identify hidden coupling around {signal}.",
            "Audit an architecture change for {team} where {issue} crosses queue, planner, and executor boundaries.",
        ),
        max_tokens_range=(200, 380),
        temperature_range=(0.05, 0.20),
        interactive_weight=0.70,
        high_priority_weight=0.45,
        mid_priority_weight=0.40,
    ),
    Archetype(
        key="general",
        system_tags="chat writing summarize qa general instruction efficient",
        followups=(
            "Keep replies practical and brief.",
            "Favor quick summarization and lightweight instruction following.",
        ),
        prompts=(
            "Rewrite a messy handoff for {team} into a short customer-ready update mentioning {signal}.",
            "Summarize a brief incident note from {place} involving {material} and {animal}; keep it actionable.",
            "Turn a rough project message for {domain} into three crisp bullets.",
            "Draft a compact status note about {issue} in {place}; keep it one step ahead.",
        ),
        max_tokens_range=(100, 200),
        temperature_range=(0.10, 0.35),
        interactive_weight=0.88,
        high_priority_weight=0.20,
        mid_priority_weight=0.55,
    ),
    Archetype(
        key="reasoning",
        system_tags="reasoning math logic analysis problem solving technical",
        followups=(
            "Show structured reasoning and technical rigor.",
            "Prefer explicit logical analysis over stylistic polish.",
        ),
        prompts=(
            "Reason through a technical incident in {domain} where {signal} and {issue} disagree; find the root cause.",
            "Analyze a tricky logic bug in a planner path used by {role}; justify the best correction.",
            "Diagnose why queue growth in {place} contradicts telemetry after {animal} was marked healthy.",
            "Solve a prioritization problem for {domain} involving {signal} and one hard constraint.",
        ),
        max_tokens_range=(180, 320),
        temperature_range=(0.05, 0.18),
        interactive_weight=0.78,
        high_priority_weight=0.40,
        mid_priority_weight=0.42,
    ),
)

ARCHETYPE_BY_KEY = {a.key: a for a in ARCHETYPES}

LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Python")
DOMAINS = ("education", "energy", "retail", "climate", "transit", "health")
PLACES = ("library", "harbor", "orchard", "bridge", "atrium", "workshop")
ROLES = ("analyst", "designer", "coordinator", "operator", "planner", "reviewer")
TEAMS = ("studio team", "ops channel", "platform group", "service owners")
SIGNALS = ("amber warning", "jade queue", "teal marker", "silver incident tag")
MATERIALS = ("basalt", "bamboo", "cedar", "copper", "glass", "granite")
ANIMALS = ("otter", "lynx", "heron", "falcon", "lemur", "beetle")
ISSUES = ("missing ownership", "drifting latency", "flaky retries", "contradictory telemetry")
MODULES = (
    ("queue", "planner", "executor"),
    ("scheduler", "monitor", "recorder"),
    ("policy engine", "resolver", "executor"),
)


def _choose_priority(archetype: Archetype, rng: random.Random) -> str:
    if rng.random() < archetype.high_priority_weight:
        return "high"
    if rng.random() < archetype.mid_priority_weight / max(1e-9, 1.0 - archetype.high_priority_weight):
        return "mid"
    return "low"


def _choose_mode(archetype: Archetype, rng: random.Random) -> str:
    return "interactive" if rng.random() < archetype.interactive_weight else "batch"


def _build_payload(archetype: Archetype, rng: random.Random) -> dict:
    module_a, module_b, module_c = rng.choice(MODULES)
    system_msg = f"Prefer {archetype.system_tags}. {rng.choice(archetype.followups)}"
    user_msg = rng.choice(archetype.prompts).format(
        language=rng.choice(LANGUAGES),
        domain=rng.choice(DOMAINS),
        place=rng.choice(PLACES),
        role=rng.choice(ROLES),
        team=rng.choice(TEAMS),
        signal=rng.choice(SIGNALS),
        material=rng.choice(MATERIALS),
        animal=rng.choice(ANIMALS),
        issue=rng.choice(ISSUES),
        module_a=module_a,
        module_b=module_b,
        module_c=module_c,
    )
    return {
        "stream": True,
        "max_tokens": rng.randint(*archetype.max_tokens_range),
        "temperature": round(rng.uniform(*archetype.temperature_range), 2),
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }


@dataclass(frozen=True)
class BurstWindow:
    """One activity window within the 10-minute schedule."""
    start_ms: int
    end_ms: int
    request_count: int


def _make_windows(
    total_requests: int,
    num_windows: int,
    window_duration_s: int,
    gap_duration_s: int,
) -> list[BurstWindow]:
    """Create evenly-spaced burst windows with gaps between them."""
    per_window_base = total_requests // num_windows
    remainder = total_requests % num_windows
    windows = []
    for i in range(num_windows):
        start_s = i * (window_duration_s + gap_duration_s)
        count = per_window_base + (1 if i < remainder else 0)
        windows.append(BurstWindow(
            start_ms=start_s * 1000,
            end_ms=(start_s + window_duration_s) * 1000,
            request_count=count,
        ))
    return windows


def _distribute_in_window(
    window: BurstWindow,
    rng: random.Random,
) -> list[int]:
    """Place requests within a window using sub-burst clustering."""
    duration_ms = window.end_ms - window.start_ms
    n = window.request_count
    if n == 0:
        return []

    # 2-3 sub-burst centers within the window
    num_centers = min(n, rng.randint(2, 3))
    margin = int(duration_ms * 0.05)
    centers = sorted(
        rng.randint(margin, duration_ms - margin) for _ in range(num_centers)
    )

    offsets = []
    for _ in range(n):
        center = rng.choice(centers)
        spread = rng.gauss(0, duration_ms * 0.08)
        raw = center + int(spread) + rng.randint(0, 200)
        clamped = max(0, min(duration_ms - 1, raw))
        offsets.append(window.start_ms + clamped)

    offsets.sort()
    return offsets


def build_ablation_workload(
    total_requests: int,
    num_windows: int,
    window_duration_s: int,
    gap_duration_s: int,
    seed_suffix: str,
) -> list[dict[str, str]]:
    """Build a resource-mode workload with burst-gap arrival pattern."""
    rng = random.Random(f"{SEED}-{seed_suffix}")

    windows = _make_windows(total_requests, num_windows, window_duration_s, gap_duration_s)

    # Interleave archetype assignment across all requests
    archetype_keys = [a.key for a in ARCHETYPES]
    request_archetypes = []
    for i in range(total_requests):
        request_archetypes.append(archetype_keys[i % len(archetype_keys)])
    rng.shuffle(request_archetypes)

    # Collect all offsets across windows
    all_offsets = []
    for window in windows:
        all_offsets.extend(_distribute_in_window(window, rng))

    all_offsets.sort()
    assert len(all_offsets) == total_requests

    counters: dict[str, int] = {k: 0 for k in archetype_keys}
    rows = []
    for offset_ms, arch_key in zip(all_offsets, request_archetypes):
        archetype = ARCHETYPE_BY_KEY[arch_key]
        counters[arch_key] += 1
        request_id = f"ablation-{arch_key}-{counters[arch_key]:04d}"
        payload = _build_payload(archetype, rng)
        rows.append({
            "request_id": request_id,
            "arrival_offset": str(offset_ms),
            "mode": _choose_mode(archetype, rng),
            "priority": _choose_priority(archetype, rng),
            "body_json": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        })

    rows.sort(key=lambda r: (int(r["arrival_offset"]), r["request_id"]))
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["request_id", "arrival_offset", "mode", "priority", "body_json"],
        )
        writer.writeheader()
        writer.writerows(rows)


VARIANTS = (
    {
        "name": "150_burst5_gap70",
        "total": 150,
        "num_windows": 5,
        "window_s": 50,
        "gap_s": 70,
        "desc": "5 windows × 50s active / 70s gap — models sleep deeply between bursts",
    },
    {
        "name": "150_burst5_gap30",
        "total": 150,
        "num_windows": 5,
        "window_s": 50,
        "gap_s": 30,
        "desc": "5 windows × 50s active / 30s gap — shorter gaps, some models may stay warm",
    },
    {
        "name": "150_burst8_gap20",
        "total": 150,
        "num_windows": 8,
        "window_s": 30,
        "gap_s": 20,
        "desc": "8 windows × 30s active / 20s gap — frequent small bursts",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate resource-mode workloads for ECCS ablation benchmarks.",
    )
    parser.add_argument(
        "--root",
        default="tests/performance/workloads/ablation",
        help="Root output directory.",
    )
    args = parser.parse_args()
    root = Path(args.root)

    for v in VARIANTS:
        rows = build_ablation_workload(
            total_requests=v["total"],
            num_windows=v["num_windows"],
            window_duration_s=v["window_s"],
            gap_duration_s=v["gap_s"],
            seed_suffix=v["name"],
        )
        path = root / f"workload_{v['name']}.csv"
        write_csv(path, rows)
        print(f"Wrote {len(rows):>4d} requests to {path}")
        print(f"       {v['desc']}")

        # Print arrival window summary
        windows = _make_windows(v["total"], v["num_windows"], v["window_s"], v["gap_s"])
        for i, w in enumerate(windows):
            print(f"       Window {i+1}: {w.start_ms/1000:.0f}s-{w.end_ms/1000:.0f}s "
                  f"({w.request_count} reqs)")

    print("\nWeight scenarios (set at runtime via ECCS_WEIGHT_OVERRIDE):")
    print("  tight:   {\"1\": 10.0, \"2\": 9.5, \"3\": 9.0}")
    print("  medium:  {\"1\": 10.0, \"2\": 7.0, \"3\": 4.0}")
    print("  wide:    {\"1\": 10.0, \"2\": 2.0, \"3\": 1.0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
