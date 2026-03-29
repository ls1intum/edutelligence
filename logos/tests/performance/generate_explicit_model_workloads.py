"""Generate bursty direct-model workloads for explicit scheduling benchmarks.

The generated CSVs:
- use explicit ``model`` routing (no classification)
- preserve the same skewed model distribution as the resource-mode benchmark
- cluster same-model requests into bursts to stress per-model parallelism
- write both a 60-minute and a 10-minute variant into explicit-duration folders
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


SEED = 20260329
WINDOWS_MS = {
    "60m": 60 * 60 * 1000,
    "10m": 10 * 60 * 1000,
}
TOTAL_REQUESTS = {
    "60m": 500,
    "10m": 84,
}


@dataclass(frozen=True)
class Archetype:
    key: str
    model_name: str
    base_count_60m: int
    prompts: tuple[str, ...]
    max_tokens_range: tuple[int, int]
    temperature_range: tuple[float, float]
    interactive_weight: float
    high_priority_weight: float
    mid_priority_weight: float


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        key="coder7",
        model_name="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        base_count_60m=130,
        prompts=(
            "Patch a small {language} handler used by {team}; keep the diff short and add two focused regression tests.",
            "Refactor a lightweight {language} helper for {domain} after {issue}; propose the minimal safe fix and quick validation.",
            "Debug a compact {language} endpoint in {place} where {signal} exposes a brittle edge; stay implementation-first.",
            "Repair a tiny {language} utility after a {material} mismatch caused {issue}; prefer the smallest safe change.",
            "Tighten a short {language} parser for {team}; remove the flaky branch around {signal} and call out one test to add.",
        ),
        max_tokens_range=(160, 260),
        temperature_range=(0.05, 0.25),
        interactive_weight=0.82,
        high_priority_weight=0.28,
        mid_priority_weight=0.54,
    ),
    Archetype(
        key="coder14",
        model_name="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
        base_count_60m=90,
        prompts=(
            "Diagnose a complex {language} scheduling regression across {module_a}, {module_b}, and {module_c}; explain the safest rollout.",
            "Compare two backend designs for a {domain} service after {signal} exposed hidden coupling; recommend one with rationale.",
            "Review a multi-module refactor in {language}; untangle {issue} across queueing, execution, and retry boundaries.",
            "Audit an architecture change for {team} where {issue} spans several layers; propose a staged migration plan.",
            "Reason through a deep concurrency failure in a {language} service for {domain}; contrast the top two fixes.",
        ),
        max_tokens_range=(220, 420),
        temperature_range=(0.05, 0.20),
        interactive_weight=0.74,
        high_priority_weight=0.42,
        mid_priority_weight=0.41,
    ),
    Archetype(
        key="general7",
        model_name="Qwen/Qwen2.5-7B-Instruct-AWQ",
        base_count_60m=125,
        prompts=(
            "Rewrite a messy handoff for {team} into a short customer-ready update that mentions {signal} and one next step.",
            "Summarize a brief incident note from {place} involving {material} and {animal}; keep it tight and actionable.",
            "Convert a rough project note for {domain} into three crisp bullets without changing the meaning.",
            "Draft a compact support reply for {role} about {issue}; keep the tone practical and brief.",
            "Condense a noisy status thread from {team} into a direct handoff with one action item.",
        ),
        max_tokens_range=(100, 200),
        temperature_range=(0.10, 0.35),
        interactive_weight=0.88,
        high_priority_weight=0.18,
        mid_priority_weight=0.61,
    ),
    Archetype(
        key="general14",
        model_name="Qwen/Qwen2.5-14B-Instruct-AWQ",
        base_count_60m=45,
        prompts=(
            "Synthesize several conflicting updates for {domain} into a detailed recommendation memo with rationale and risks.",
            "Compare contradictory rollout notes from {team} about {issue}; produce a nuanced recommendation with tradeoffs.",
            "Create a longer-form decision brief for {role} after {signal} exposed uncertainty across timing and customer impact.",
            "Merge scattered project notes from {place} into a coherent analysis with recommendation, risk, and communication guidance.",
            "Write a thoughtful summary for leadership on {domain}; balance timing, cost, and stakeholder concerns around {material}.",
        ),
        max_tokens_range=(220, 360),
        temperature_range=(0.08, 0.25),
        interactive_weight=0.62,
        high_priority_weight=0.34,
        mid_priority_weight=0.46,
    ),
    Archetype(
        key="deepseek",
        model_name="casperhansen/deepseek-r1-distill-llama-8b-awq",
        base_count_60m=110,
        prompts=(
            "Reason step by step through a technical incident in {domain} where {signal} and {issue} disagree; find the likeliest root cause.",
            "Work through a capacity-planning problem for {team}; explain where the assumptions around {material} break.",
            "Analyze a tricky logic bug in a planner path used by {role}; justify the best correction and its main tradeoff.",
            "Diagnose why queue growth in {place} contradicts the telemetry after {animal} was marked healthy; defend the best explanation.",
            "Solve a prioritization problem for {domain} involving {signal}, delayed ownership, and one hard constraint; show the decision path.",
        ),
        max_tokens_range=(190, 340),
        temperature_range=(0.05, 0.18),
        interactive_weight=0.79,
        high_priority_weight=0.39,
        mid_priority_weight=0.44,
    ),
)


LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Python")
DOMAINS = ("education", "energy", "retail", "climate", "transit", "health", "logistics", "agriculture")
PLACES = ("library", "harbor", "orchard", "bridge", "atrium", "greenhouse", "workshop", "station", "rooftop")
ROLES = ("analyst", "designer", "navigator", "coordinator", "operator", "planner", "editor", "reviewer")
TEAMS = ("studio team", "ops channel", "platform group", "customer desk", "service owners", "release crew")
SIGNALS = ("amber warning", "navy window", "jade queue", "teal marker", "silver incident tag", "cobalt fallback")
MATERIALS = ("basalt", "bamboo", "cedar", "copper", "glass", "granite", "linen", "clay", "steel")
ANIMALS = ("otter", "lynx", "heron", "ibis", "falcon", "lemur", "yak", "beetle", "orca", "stoat")
ISSUES = ("missing ownership", "conflicting rollout dates", "drifting latency", "flaky retries", "unclear rollback rules", "contradictory telemetry")
MODULES = (
    ("queue", "planner", "executor"),
    ("scheduler", "monitor", "recorder"),
    ("policy engine", "resolver", "executor"),
    ("router", "queue", "billing"),
)


def choose_priority(archetype: Archetype, rng: random.Random) -> str:
    if rng.random() < archetype.high_priority_weight:
        return "high"
    if rng.random() < archetype.mid_priority_weight / max(1e-9, 1.0 - archetype.high_priority_weight):
        return "mid"
    return "low"


def choose_mode(archetype: Archetype, rng: random.Random) -> str:
    return "interactive" if rng.random() < archetype.interactive_weight else "batch"


def scaled_counts(total_requests: int) -> dict[str, int]:
    raw = []
    for archetype in ARCHETYPES:
        scaled = archetype.base_count_60m * total_requests / TOTAL_REQUESTS["60m"]
        raw.append((archetype.key, scaled))
    counts = {key: int(value) for key, value in raw}
    remainder = total_requests - sum(counts.values())
    ranked = sorted(raw, key=lambda item: item[1] - int(item[1]), reverse=True)
    for key, _ in ranked[:remainder]:
        counts[key] += 1
    return counts


def weighted_choice(rng: random.Random, weighted_keys: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in weighted_keys)
    needle = rng.random() * total
    running = 0.0
    for key, weight in weighted_keys:
        running += weight
        if needle <= running:
            return key
    return weighted_keys[-1][0]


def build_bursts(counts: dict[str, int], rng: random.Random) -> list[tuple[str, int]]:
    remaining = dict(counts)
    bursts: list[tuple[str, int]] = []
    while sum(remaining.values()) > 0:
        candidates = [(key, float(value)) for key, value in remaining.items() if value > 0]
        key = weighted_choice(rng, candidates)
        remaining_for_key = remaining[key]
        if remaining_for_key <= 3:
            burst_size = remaining_for_key
        else:
            burst_size = min(remaining_for_key, rng.randint(3, 8))
            if remaining_for_key - burst_size == 1:
                burst_size -= 1
        bursts.append((key, burst_size))
        remaining[key] -= burst_size
    return bursts


def build_burst_anchors(duration_ms: int, burst_count: int, rng: random.Random) -> list[int]:
    minute_count = max(1, duration_ms // 60_000)
    weights = []
    for minute in range(minute_count):
        wave = 0.75 + 0.55 * (1.0 + math.sin((minute / max(1, minute_count)) * math.tau * 2.5 + 0.9))
        burst = rng.choice((0.55, 0.8, 1.0, 1.3, 1.7, 2.2, 3.0))
        weights.append(wave * burst * rng.uniform(0.7, 1.4))

    scaled = [burst_count * weight / sum(weights) for weight in weights]
    per_minute = [int(value) for value in scaled]
    remainder = burst_count - sum(per_minute)
    ranked = sorted(enumerate(scaled), key=lambda item: item[1] - int(item[1]), reverse=True)
    for idx, _ in ranked[:remainder]:
        per_minute[idx] += 1

    anchors: list[int] = []
    for minute, count in enumerate(per_minute):
        if count <= 0:
            continue
        cluster_count = min(count, rng.choice((1, 1, 2, 2, 3)))
        centers = sorted(rng.uniform(2.0, 57.0) for _ in range(cluster_count))
        for _ in range(count):
            center = rng.choice(centers)
            seconds = max(0.0, min(59.8, rng.gauss(center, rng.uniform(0.6, 3.2))))
            anchor = minute * 60_000 + int(seconds * 1000) + rng.randint(0, 250)
            anchors.append(min(anchor, duration_ms - 1))

    anchors.sort()
    return anchors


def build_payload(archetype: Archetype, rng: random.Random) -> dict:
    language = rng.choice(LANGUAGES)
    domain = rng.choice(DOMAINS)
    place = rng.choice(PLACES)
    role = rng.choice(ROLES)
    team = rng.choice(TEAMS)
    signal = rng.choice(SIGNALS)
    material = rng.choice(MATERIALS)
    animal = rng.choice(ANIMALS)
    issue = rng.choice(ISSUES)
    module_a, module_b, module_c = rng.choice(MODULES)

    system = "Follow the user instructions exactly. Keep the answer concise unless the task clearly needs detail."
    user = rng.choice(archetype.prompts).format(
        animal=animal,
        domain=domain,
        issue=issue,
        language=language,
        material=material,
        module_a=module_a,
        module_b=module_b,
        module_c=module_c,
        place=place,
        role=role,
        signal=signal,
        team=team,
    )
    return {
        "model": archetype.model_name,
        "stream": True,
        "max_tokens": rng.randint(*archetype.max_tokens_range),
        "temperature": round(rng.uniform(*archetype.temperature_range), 2),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def build_rows(duration_key: str, rng: random.Random) -> list[dict[str, str]]:
    duration_ms = WINDOWS_MS[duration_key]
    total_requests = TOTAL_REQUESTS[duration_key]
    counts = scaled_counts(total_requests)
    archetype_by_key = {archetype.key: archetype for archetype in ARCHETYPES}
    bursts = build_bursts(counts, rng)
    anchors = build_burst_anchors(duration_ms, len(bursts), rng)
    counters = {archetype.key: 0 for archetype in ARCHETYPES}
    rows: list[dict[str, str]] = []

    for anchor, (key, burst_size) in zip(anchors, bursts, strict=True):
        archetype = archetype_by_key[key]
        offset = anchor
        for idx in range(burst_size):
            counters[key] += 1
            request_id = f"explicit-{key}-{counters[key]:04d}"
            if idx == 0:
                offset = min(anchor + rng.randint(0, 80), duration_ms - 1)
            else:
                step = rng.randint(25, 220 if idx < 3 else 950)
                offset = min(offset + step, duration_ms - 1)
            payload = build_payload(archetype, rng)
            rows.append(
                {
                    "request_id": request_id,
                    "arrival_offset": str(offset),
                    "mode": choose_mode(archetype, rng),
                    "priority": choose_priority(archetype, rng),
                    "body_json": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                }
            )

    rows.sort(key=lambda row: (float(row["arrival_offset"]), row["request_id"]))
    if len(rows) != total_requests:
        raise ValueError(f"Expected {total_requests} rows for {duration_key}, built {len(rows)}")
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["request_id", "arrival_offset", "mode", "priority", "body_json"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate bursty direct-model benchmark workloads.")
    parser.add_argument(
        "--root",
        default="tests/performance/workloads/explicit",
        help="Root directory for generated workload folders.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    outputs = {
        "60m": root / "60m" / "workload_explicit_local5_skewed_bursty_60m.csv",
        "10m": root / "10m" / "workload_explicit_local5_skewed_bursty_10m.csv",
    }

    for duration_key in ("60m", "10m"):
        rng = random.Random(f"{SEED}-{duration_key}")
        rows = build_rows(duration_key, rng)
        write_csv(outputs[duration_key], rows)
        print(f"Wrote {len(rows)} requests to {outputs[duration_key]}")

    print("60m base distribution:")
    for archetype in ARCHETYPES:
        print(f"  {archetype.key}: {archetype.base_count_60m} -> {archetype.model_name}")
    print("10m scaled distribution:")
    for key, count in scaled_counts(TOTAL_REQUESTS['10m']).items():
        model_name = next(archetype.model_name for archetype in ARCHETYPES if archetype.key == key)
        print(f"  {key}: {count} -> {model_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
