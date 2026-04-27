"""Generate direct-model workloads for explicit scheduling benchmarks.

The generated CSVs:
- use explicit ``model`` routing (no classification)
- preserve the configured model distribution for each benchmark variant
- support both same-model burst clustering and randomized interleaving
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

LAYOUT_BURSTY = "bursty"
LAYOUT_INTERLEAVED = "interleaved_random"


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
    use_system_message: bool = True


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
        key="mistral7",
        model_name="solidrust/Mistral-7B-Instruct-v0.3-AWQ",
        base_count_60m=125,
        prompts=(
            "Rewrite a messy handoff for {team} into a short customer-ready update that mentions {signal} and one next step.",
            "Summarize a brief incident note from {place} involving {material} and {animal}; keep it tight and actionable.",
            "Convert a rough project note for {domain} into three crisp bullets without changing the meaning.",
            "Draft a compact support reply for {role} about {issue}; keep the tone practical and brief.",
            "Condense a noisy status thread from {team} into a direct handoff with one action item.",
        ),
        max_tokens_range=(110, 220),
        temperature_range=(0.10, 0.32),
        interactive_weight=0.86,
        high_priority_weight=0.20,
        mid_priority_weight=0.58,
        use_system_message=False,
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

ARCHETYPE_BY_KEY = {archetype.key: archetype for archetype in ARCHETYPES}

VARIANTS = (
    {
        "name": "60m",
        "duration_ms": WINDOWS_MS["60m"],
        "total_requests": TOTAL_REQUESTS["60m"],
        "archetype_keys": ("coder7", "coder14", "general7", "general14", "deepseek"),
        "seed_suffix": "60m",
        "output_relpath": Path("60m") / "workload_explicit_local5_skewed_bursty_60m.csv",
    },
    {
        "name": "10m",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": TOTAL_REQUESTS["10m"],
        "archetype_keys": ("coder7", "coder14", "general7", "general14", "deepseek"),
        "seed_suffix": "10m",
        "output_relpath": Path("10m") / "workload_explicit_local5_skewed_bursty_10m.csv",
    },
    {
        "name": "10m_no_coder14_200",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 200,
        "archetype_keys": ("coder7", "general7", "general14", "deepseek"),
        "seed_suffix": "10m-no-coder14-200",
        "output_relpath": Path("10m") / "workload_explicit_local4_no_coder14_bursty_200_10m.csv",
    },
    {
        "name": "10m_mistral_deepseek_200",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 200,
        "archetype_keys": ("mistral7", "deepseek"),
        "seed_suffix": "10m-mistral-deepseek-200",
        "output_relpath": Path("10m") / "workload_explicit_local2_mistral_deepseek_bursty_200_10m.csv",
    },
    {
        "name": "10m_mistral_deepseek_500",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 500,
        "archetype_keys": ("mistral7", "deepseek"),
        "seed_suffix": "10m-mistral-deepseek-500",
        "output_relpath": Path("10m") / "workload_explicit_local2_mistral_deepseek_bursty_500_10m.csv",
    },
    {
        "name": "10m_coder3_even_random_150",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 150,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-random-150",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_random_150_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 50,
            "coder14": 50,
            "deepseek": 50,
        },
    },
    {
        "name": "10m_coder3_even_random_300",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 300,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-random-300",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_random_300_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 100,
            "coder14": 100,
            "deepseek": 100,
        },
    },
    {
        "name": "10m_coder3_even_random_600",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 600,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-random-600",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_random_600_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 200,
            "coder14": 200,
            "deepseek": 200,
        },
    },
    {
        "name": "10m_coder3_even_bursty_150",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 150,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-bursty-150",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_bursty_150_10m.csv",
        "counts_override": {
            "coder7": 50,
            "coder14": 50,
            "deepseek": 50,
        },
    },
    {
        "name": "10m_coder3_even_bursty_300",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 300,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-bursty-300",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_bursty_300_10m.csv",
        "counts_override": {
            "coder7": 100,
            "coder14": 100,
            "deepseek": 100,
        },
    },
    {
        "name": "10m_coder3_even_bursty_600",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 600,
        "archetype_keys": ("coder7", "coder14", "deepseek"),
        "seed_suffix": "10m-coder3-even-bursty-600",
        "output_relpath": Path("10m") / "workload_explicit_coder3_even_bursty_600_10m.csv",
        "counts_override": {
            "coder7": 200,
            "coder14": 200,
            "deepseek": 200,
        },
    },
    {
        "name": "10m_local3_even_random_600",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 600,
        "archetype_keys": ("mistral7", "deepseek", "coder7"),
        "seed_suffix": "10m-local3-even-random-600",
        "output_relpath": Path("10m") / "workload_explicit_local3_even_random_600_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "mistral7": 200,
            "deepseek": 200,
            "coder7": 200,
        },
    },
    {
        "name": "10m_hw3_even_random_150",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 150,
        "archetype_keys": ("coder7", "coder14", "mistral7"),
        "seed_suffix": "10m-hw3-even-random-150",
        "output_relpath": Path("10m") / "workload_explicit_hw3_even_random_150_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 50,
            "coder14": 50,
            "mistral7": 50,
        },
    },
    {
        "name": "10m_hw3_even_bursty_150",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 150,
        "archetype_keys": ("coder7", "coder14", "mistral7"),
        "seed_suffix": "10m-hw3-even-bursty-150",
        "output_relpath": Path("10m") / "workload_explicit_hw3_even_bursty_150_10m.csv",
        "counts_override": {
            "coder7": 50,
            "coder14": 50,
            "mistral7": 50,
        },
    },
    {
        "name": "10m_hw3_even_random_300",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 300,
        "archetype_keys": ("coder7", "coder14", "mistral7"),
        "seed_suffix": "10m-hw3-even-random-300",
        "output_relpath": Path("10m") / "workload_explicit_hw3_even_random_300_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 100,
            "coder14": 100,
            "mistral7": 100,
        },
    },
    {
        "name": "10m_hw3_even_random_600",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 600,
        "archetype_keys": ("coder7", "coder14", "mistral7"),
        "seed_suffix": "10m-hw3-even-random-600",
        "output_relpath": Path("10m") / "workload_explicit_hw3_even_random_600_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 200,
            "coder14": 200,
            "mistral7": 200,
        },
    },
    {
        "name": "10m_hw3_even_random_1200",
        "duration_ms": WINDOWS_MS["10m"],
        "total_requests": 1200,
        "archetype_keys": ("coder7", "coder14", "mistral7"),
        "seed_suffix": "10m-hw3-even-random-1200",
        "output_relpath": Path("10m") / "workload_explicit_hw3_even_random_1200_10m.csv",
        "layout": LAYOUT_INTERLEAVED,
        "counts_override": {
            "coder7": 400,
            "coder14": 400,
            "mistral7": 400,
        },
    },
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


def scaled_counts(total_requests: int, archetypes: tuple[Archetype, ...]) -> dict[str, int]:
    base_total = sum(archetype.base_count_60m for archetype in archetypes)
    if base_total <= 0:
        raise ValueError("Archetype set must have a positive base request total")
    raw = []
    for archetype in archetypes:
        scaled = archetype.base_count_60m * total_requests / base_total
        raw.append((archetype.key, scaled))
    counts = {key: int(value) for key, value in raw}
    remainder = total_requests - sum(counts.values())
    ranked = sorted(raw, key=lambda item: item[1] - int(item[1]), reverse=True)
    for key, _ in ranked[:remainder]:
        counts[key] += 1
    return counts


def resolve_counts(variant: dict, archetypes: tuple[Archetype, ...]) -> dict[str, int]:
    override = variant.get("counts_override")
    if override is None:
        return scaled_counts(int(variant["total_requests"]), archetypes)

    counts = {archetype.key: 0 for archetype in archetypes}
    for key, value in override.items():
        if key not in counts:
            raise ValueError(f"Unknown archetype key in counts_override: {key}")
        counts[key] = int(value)
    total = sum(counts.values())
    expected = int(variant["total_requests"])
    if total != expected:
        raise ValueError(f"counts_override totals {total}, expected {expected}")
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


def build_random_offsets(duration_ms: int, total_requests: int, rng: random.Random) -> list[int]:
    minute_count = max(1, duration_ms // 60_000)
    weights = []
    for minute in range(minute_count):
        wave = 0.8 + 0.5 * (1.0 + math.sin((minute / max(1, minute_count)) * math.tau * 2.2 + 0.4))
        burst = rng.choice((0.65, 0.85, 1.0, 1.15, 1.35, 1.8, 2.4))
        weights.append(wave * burst * rng.uniform(0.75, 1.35))

    scaled = [total_requests * weight / sum(weights) for weight in weights]
    per_minute = [int(value) for value in scaled]
    remainder = total_requests - sum(per_minute)
    ranked = sorted(enumerate(scaled), key=lambda item: item[1] - int(item[1]), reverse=True)
    for idx, _ in ranked[:remainder]:
        per_minute[idx] += 1

    offsets: list[int] = []
    for minute, count in enumerate(per_minute):
        if count <= 0:
            continue
        cluster_count = max(1, min(count, rng.choice((2, 3, 4))))
        centers = sorted(rng.uniform(1.5, 58.0) for _ in range(cluster_count))
        for _ in range(count):
            center = rng.choice(centers)
            seconds = max(0.0, min(59.8, rng.gauss(center, rng.uniform(0.5, 4.6))))
            offsets.append(min(duration_ms - 1, minute * 60_000 + int(seconds * 1000) + rng.randint(0, 250)))

    offsets.sort()
    return offsets


def build_interleaved_sequence(counts: dict[str, int], rng: random.Random) -> list[str]:
    remaining = dict(counts)
    sequence: list[str] = []

    while sum(remaining.values()) > 0:
        candidates = [
            (key, float(value))
            for key, value in remaining.items()
            if value > 0 and not (len(sequence) >= 2 and sequence[-1] == key and sequence[-2] == key)
        ]
        if not candidates:
            candidates = [(key, float(value)) for key, value in remaining.items() if value > 0]
        key = weighted_choice(rng, candidates)
        sequence.append(key)
        remaining[key] -= 1

    return sequence


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
    if archetype.use_system_message:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    else:
        messages = [
            {"role": "user", "content": f"{system}\n\n{user}"},
        ]
    return {
        "model": archetype.model_name,
        "stream": True,
        "max_tokens": rng.randint(*archetype.max_tokens_range),
        "temperature": round(rng.uniform(*archetype.temperature_range), 2),
        "messages": messages,
    }


def build_rows(
    duration_ms: int,
    total_requests: int,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
    *,
    counts: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    counts = counts or scaled_counts(total_requests, archetypes)
    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    bursts = build_bursts(counts, rng)
    anchors = build_burst_anchors(duration_ms, len(bursts), rng)
    counters = {archetype.key: 0 for archetype in archetypes}
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
        raise ValueError(f"Expected {total_requests} rows, built {len(rows)}")
    return rows


def build_interleaved_rows(
    duration_ms: int,
    total_requests: int,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
    *,
    counts: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    counts = counts or scaled_counts(total_requests, archetypes)
    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    sequence = build_interleaved_sequence(counts, rng)
    offsets = build_random_offsets(duration_ms, len(sequence), rng)
    counters = {archetype.key: 0 for archetype in archetypes}
    rows: list[dict[str, str]] = []

    for offset, key in zip(offsets, sequence, strict=True):
        archetype = archetype_by_key[key]
        counters[key] += 1
        request_id = f"explicit-{key}-{counters[key]:04d}"
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
        raise ValueError(f"Expected {total_requests} rows, built {len(rows)}")
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
    for variant in VARIANTS:
        archetypes = tuple(ARCHETYPE_BY_KEY[key] for key in variant["archetype_keys"])
        rng = random.Random(f"{SEED}-{variant['seed_suffix']}")
        counts = resolve_counts(variant, archetypes)
        layout = str(variant.get("layout") or LAYOUT_BURSTY)
        if layout == LAYOUT_INTERLEAVED:
            rows = build_interleaved_rows(
                variant["duration_ms"],
                variant["total_requests"],
                archetypes,
                rng,
                counts=counts,
            )
        else:
            rows = build_rows(
                variant["duration_ms"],
                variant["total_requests"],
                archetypes,
                rng,
                counts=counts,
            )
        output_path = root / variant["output_relpath"]
        write_csv(output_path, rows)
        print(f"Wrote {len(rows)} requests to {output_path}")

    print("Variant distributions:")
    for variant in VARIANTS:
        archetypes = tuple(ARCHETYPE_BY_KEY[key] for key in variant["archetype_keys"])
        print(f"  {variant['name']}:")
        for key, count in resolve_counts(variant, archetypes).items():
            model_name = ARCHETYPE_BY_KEY[key].model_name
            print(f"    {key}: {count} -> {model_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
