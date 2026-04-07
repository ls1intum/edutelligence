"""Generate deterministic resource-mode workloads with skewed classification targets.

The generated workloads:
- stay in resource mode by omitting the ``model`` field
- bias initial classification toward five local models
- keep cloud models available as fallback candidates during live scheduling
- cluster similar requests into same-model bursts to stress queueing and parallelism

Example:
    python3 tests/performance/generate_resource_mode_workload.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


SEED = 20260329
TOTAL_REQUESTS = {
    "60m": 500,
    "10m": 84,
}
WINDOWS_MS = {
    "60m": 60 * 60 * 1000,
    "10m": 10 * 60 * 1000,
}


@dataclass(frozen=True)
class Archetype:
    key: str
    model_name: str
    system_tags: str
    followups: tuple[str, ...]
    prompts: tuple[str, ...]
    count: int
    max_tokens_range: tuple[int, int]
    temperature_range: tuple[float, float]
    interactive_weight: float
    high_priority_weight: float
    mid_priority_weight: float


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        key="coder7",
        model_name="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        system_tags="coding code python typescript debugging refactor tests efficient fast",
        followups=(
            "Favor low-latency implementation help.",
            "Keep the answer patch-focused and compact.",
            "Bias toward the smallest safe fix and direct tests.",
        ),
        prompts=(
            "Patch a small {language} handler that breaks when {signal} appears in {place}; keep the change short and name two regression tests.",
            "Refactor a lightweight {language} helper for {domain} so {issue}; return the minimal safe diff plan and one focused test.",
            "Debug a compact {language} endpoint where {role} reports {issue}; propose a fast fix and concise validation steps.",
            "Tighten a tiny {language} parser used by {team}; remove the flaky edge around {signal} and keep the answer implementation-first.",
            "Repair a short {language} auth utility after a {material} mismatch caused {issue}; explain the smallest low-risk patch.",
            "Update a small queue helper for {domain}; simplify the control flow, preserve behavior, and call out the tests to add.",
            "Fix a flaky {language} validator used in {place}; keep the churn low and suggest one compact benchmark check.",
            "Review a brief {language} patch for {team}; point out the bug around {signal} and propose the shortest robust correction.",
        ),
        count=130,
        max_tokens_range=(160, 260),
        temperature_range=(0.05, 0.25),
        interactive_weight=0.82,
        high_priority_weight=0.28,
        mid_priority_weight=0.54,
    ),
    Archetype(
        key="coder14",
        model_name="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
        system_tags="coding code python typescript architecture refactor debugging reasoning complex",
        followups=(
            "Optimize for deeper code reasoning over speed.",
            "Prefer architectural tradeoffs and explicit failure analysis.",
            "Bias toward careful debugging across module boundaries.",
        ),
        prompts=(
            "Diagnose a complex {language} scheduling regression across {module_a}, {module_b}, and {module_c}; explain the root cause and safest rollout.",
            "Compare two backend designs for a {domain} policy engine after {role} reports {issue}; recommend one and justify the migration path.",
            "Review a multi-module refactor in {language}; identify hidden coupling around {signal} and propose a staged correction plan.",
            "Untangle a deep request-pipeline failure involving retries, {material}, and logging in {place}; reason through the best structural fix.",
            "Audit an architecture change for {team} where {issue} crosses queue, planner, and executor boundaries; explain the right boundary split.",
            "Investigate a concurrency bug in a {language} service used by {domain}; compare two fixes and call out long-term maintenance risk.",
            "Evaluate a large refactor proposal after {signal} exposed fragile ownership in {place}; describe the safest sequence of changes.",
            "Reason through a layered {language} backend redesign for {team}; surface tradeoffs between throughput, clarity, and rollback safety.",
        ),
        count=90,
        max_tokens_range=(220, 420),
        temperature_range=(0.05, 0.20),
        interactive_weight=0.74,
        high_priority_weight=0.42,
        mid_priority_weight=0.41,
    ),
    Archetype(
        key="general7",
        model_name="Qwen/Qwen2.5-7B-Instruct-AWQ",
        system_tags="chat writing summarize qa general instruction efficient fast",
        followups=(
            "Keep replies practical and brief.",
            "Favor quick summarization and lightweight instruction following.",
            "Optimize for concise, clear delivery.",
        ),
        prompts=(
            "Rewrite a messy handoff for {team} into a short customer-ready update that mentions {signal} and ends with one next step.",
            "Summarize a brief incident note from {place} involving {material} and {animal}; keep it tight and actionable.",
            "Turn a rough project message for {domain} into three crisp bullets, keeping the meaning but improving clarity.",
            "Convert a noisy support update from {role} into a clean reply for {team}; mention {signal} and avoid extra detail.",
            "Draft a compact status note about {issue} in {place}; keep the tone practical and one step ahead.",
            "Write a short operator update for {domain} that connects {animal}, {material}, and {signal} without adding fluff.",
            "Condense a scattered internal thread for {team} into a direct handoff with one action item.",
            "Produce a plain-language response for {role} about {issue}; keep it brief and easy to scan.",
        ),
        count=125,
        max_tokens_range=(100, 200),
        temperature_range=(0.10, 0.35),
        interactive_weight=0.88,
        high_priority_weight=0.18,
        mid_priority_weight=0.61,
    ),
    Archetype(
        key="general14",
        model_name="Qwen/Qwen2.5-14B-Instruct-AWQ",
        system_tags="chat writing summarize qa reasoning analysis general longform",
        followups=(
            "Optimize for richer synthesis and nuance.",
            "Prefer longer-form analysis with explicit tradeoffs.",
            "Bias toward careful comparison and structured recommendations.",
        ),
        prompts=(
            "Synthesize several conflicting updates for {domain} into a detailed recommendation memo with rationale, risks, and next steps.",
            "Compare three inconsistent status notes from {team} about {issue}; produce a nuanced recommendation with tradeoffs.",
            "Write a longer-form decision brief for {role} after {signal} exposed uncertainty across staffing, timing, and customer impact.",
            "Merge scattered rollout notes from {place} into a coherent analysis with recommendation, risk, and communication guidance.",
            "Create a thoughtful summary for leadership on {domain}; balance timing, cost, and stakeholder concerns around {material}.",
            "Turn contradictory project notes from {team} into a richer recommendation that explicitly weighs uncertainty and downside.",
            "Draft a structured advisory note about {issue} in {place}; include the best option, why, and what could break.",
            "Produce a high-signal recommendation from several rough updates involving {animal}, {signal}, and delayed ownership.",
        ),
        count=45,
        max_tokens_range=(220, 360),
        temperature_range=(0.08, 0.25),
        interactive_weight=0.62,
        high_priority_weight=0.34,
        mid_priority_weight=0.46,
    ),
    Archetype(
        key="deepseek",
        model_name="casperhansen/deepseek-r1-distill-llama-8b-awq",
        system_tags="reasoning math logic analysis problem solving technical",
        followups=(
            "Show structured reasoning and technical rigor.",
            "Prefer explicit logical analysis over stylistic polish.",
            "Bias toward stepwise problem solving and defensible conclusions.",
        ),
        prompts=(
            "Reason through a technical incident in {domain} where {signal} and {issue} disagree; identify the likeliest root cause.",
            "Work step by step through a capacity-planning problem for {team}; explain where the assumptions around {material} break.",
            "Analyze a tricky logic bug in a planner path used by {role}; justify the best correction and the main tradeoff.",
            "Diagnose why queue growth in {place} contradicts the telemetry after {animal} was marked as healthy; reason to the best explanation.",
            "Solve a prioritization problem for {domain} involving {signal}, delayed ownership, and one hard constraint; show the decision path.",
            "Investigate a math-heavy estimate where {issue} appears after a {material} adjustment; explain the likely modeling mistake.",
            "Trace a technical contradiction for {team}: throughput improved, latency worsened, and {signal} stayed flat; reason to the best answer.",
            "Evaluate a failure analysis for {role} in {place}; compare explanations and defend the most plausible one.",
        ),
        count=110,
        max_tokens_range=(190, 340),
        temperature_range=(0.05, 0.18),
        interactive_weight=0.79,
        high_priority_weight=0.39,
        mid_priority_weight=0.44,
    ),
)


LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Python")
DOMAINS = (
    "education",
    "energy",
    "retail",
    "climate",
    "transit",
    "health",
    "logistics",
    "agriculture",
)
PLACES = (
    "library",
    "harbor",
    "orchard",
    "bridge",
    "atrium",
    "greenhouse",
    "workshop",
    "station",
    "rooftop",
    "courtyard",
)
ROLES = (
    "analyst",
    "designer",
    "navigator",
    "coordinator",
    "operator",
    "planner",
    "editor",
    "reviewer",
)
TEAMS = (
    "studio team",
    "ops channel",
    "platform group",
    "customer desk",
    "workshop crew",
    "service owners",
    "release crew",
    "support rotation",
)
SIGNALS = (
    "amber warning",
    "navy window",
    "jade queue",
    "teal marker",
    "silver incident tag",
    "cobalt fallback",
    "saffron alert",
    "olive dashboard flag",
)
MATERIALS = (
    "basalt",
    "bamboo",
    "cedar",
    "copper",
    "glass",
    "granite",
    "linen",
    "clay",
    "steel",
    "ink",
)
ANIMALS = (
    "otter",
    "lynx",
    "heron",
    "ibis",
    "falcon",
    "lemur",
    "yak",
    "beetle",
    "orca",
    "stoat",
)
ISSUES = (
    "missing ownership",
    "conflicting rollout dates",
    "drifting latency",
    "flaky retries",
    "broken fallback ordering",
    "unclear rollback rules",
    "a brittle edge case",
    "contradictory telemetry",
)
MODULES = (
    ("queue", "planner", "executor"),
    ("scheduler", "monitor", "recorder"),
    ("policy engine", "resolver", "executor"),
    ("router", "queue", "billing"),
)


def weighted_choice(rng: random.Random, options: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in options)
    needle = rng.random() * total
    running = 0.0
    for value, weight in options:
        running += weight
        if needle <= running:
            return value
    return options[-1][0]


def scaled_counts(total_requests: int) -> dict[str, int]:
    raw = [(archetype.key, archetype.count * total_requests / TOTAL_REQUESTS["60m"]) for archetype in ARCHETYPES]
    counts = {key: int(value) for key, value in raw}
    remainder = total_requests - sum(counts.values())
    ranked = sorted(raw, key=lambda item: item[1] - int(item[1]), reverse=True)
    for key, _ in ranked[:remainder]:
        counts[key] += 1
    return counts


def build_minute_loads(total: int, minute_count: int, rng: random.Random) -> list[int]:
    weights: list[float] = []
    for minute in range(minute_count):
        wave = 0.8 + 0.45 * (1.0 + math.sin((minute / max(1, minute_count)) * math.tau * 3.0 + 0.8))
        burst = rng.choice((0.65, 0.75, 0.9, 1.0, 1.25, 1.6, 2.1, 2.8))
        weights.append(wave * burst * rng.uniform(0.75, 1.35))

    scaled = [total * weight / sum(weights) for weight in weights]
    counts = [int(value) for value in scaled]
    remainder = total - sum(counts)
    ranked = sorted(
        enumerate(scaled),
        key=lambda item: item[1] - int(item[1]),
        reverse=True,
    )
    for idx, _ in ranked[:remainder]:
        counts[idx] += 1
    return counts


def build_burst_anchors(total_bursts: int, duration_ms: int, rng: random.Random) -> list[int]:
    minute_count = max(1, duration_ms // 60_000)
    offsets: list[int] = []
    for minute, count in enumerate(build_minute_loads(total_bursts, minute_count, rng)):
        if count == 0:
            continue
        cluster_count = min(count, rng.choice((1, 1, 2, 2, 3, 4)))
        centers = sorted(rng.uniform(2.0, 57.5) for _ in range(cluster_count))
        for _ in range(count):
            center = rng.choice(centers)
            seconds = max(0.0, min(59.95, rng.gauss(center, rng.uniform(0.45, 3.8))))
            milliseconds = minute * 60_000 + int(seconds * 1000) + rng.randint(0, 999)
            offsets.append(min(milliseconds, duration_ms - 1))

    offsets.sort()
    if len(offsets) != total_bursts:
        raise ValueError(f"Expected {total_bursts} anchors, built {len(offsets)}")
    return offsets


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


def choose_mode(archetype: Archetype, rng: random.Random) -> str:
    return "interactive" if rng.random() < archetype.interactive_weight else "batch"


def choose_priority(archetype: Archetype, rng: random.Random) -> str:
    if rng.random() < archetype.high_priority_weight:
        return "high"
    if rng.random() < archetype.mid_priority_weight / max(1e-9, 1.0 - archetype.high_priority_weight):
        return "mid"
    return "low"


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
    system = f"Prefer {archetype.system_tags}. {rng.choice(archetype.followups)}"
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
        "stream": True,
        "max_tokens": rng.randint(*archetype.max_tokens_range),
        "temperature": round(rng.uniform(*archetype.temperature_range), 2),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def build_requests(duration_key: str, rng: random.Random) -> list[dict[str, str]]:
    total_requests = TOTAL_REQUESTS[duration_key]
    duration_ms = WINDOWS_MS[duration_key]
    archetype_by_key = {archetype.key: archetype for archetype in ARCHETYPES}
    counts = scaled_counts(total_requests)
    bursts = build_bursts(counts, rng)
    anchors = build_burst_anchors(len(bursts), duration_ms, rng)
    counters: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    for anchor, (label, burst_size) in zip(anchors, bursts, strict=True):
        archetype = archetype_by_key[label]
        offset = anchor
        for idx in range(burst_size):
            counters[label] += 1
            request_id = f"resource-{label}-{counters[label]:04d}"
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
        raise ValueError(f"Expected {total_requests} requests for {duration_key}, built {len(rows)}")
    return rows


def write_workload(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["request_id", "arrival_offset", "mode", "priority", "body_json"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate skewed resource-mode performance workloads.")
    parser.add_argument(
        "--root",
        default="tests/performance/workloads/resource",
        help="Root output directory.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    outputs = {
        "60m": root / "60m" / "workload_resource_local5_skewed_bursty_60m.csv",
        "10m": root / "10m" / "workload_resource_local5_skewed_bursty_10m.csv",
    }
    for duration_key in ("60m", "10m"):
        rng = random.Random(f"{SEED}-{duration_key}")
        rows = build_requests(duration_key, rng)
        output = outputs[duration_key]
        write_workload(rows, output)
        print(f"Wrote {len(rows)} requests to {output}")

    print("60m base distribution:")
    for archetype in ARCHETYPES:
        print(f"  {archetype.key}: {archetype.count} -> {archetype.model_name}")
    print("10m scaled distribution:")
    for key, count in scaled_counts(TOTAL_REQUESTS["10m"]).items():
        model_name = next(archetype.model_name for archetype in ARCHETYPES if archetype.key == key)
        print(f"  {key}: {count} -> {model_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
