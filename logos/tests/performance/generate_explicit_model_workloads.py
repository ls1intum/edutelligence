"""Generate direct-model workloads for explicit scheduling benchmarks."""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

try:
    from .workload_layouts import (
        LAYOUT_BURSTY,
        LAYOUT_EVEN_JITTERED,
        LAYOUT_INTERLEAVED_RANDOM,
        ScenarioManifest,
        build_balanced_sequence,
        build_clustered_offsets,
        build_evenly_spaced_offsets,
        build_random_bursts,
        build_weighted_minute_loads,
        distribute_by_largest_remainder,
        partition_total_into_fixed_bursts,
        partition_total_into_bursts,
        same_model_streaks,
        weighted_choice,
        write_manifest,
    )
except ImportError:
    from workload_layouts import (
        LAYOUT_BURSTY,
        LAYOUT_EVEN_JITTERED,
        LAYOUT_INTERLEAVED_RANDOM,
        ScenarioManifest,
        build_balanced_sequence,
        build_clustered_offsets,
        build_evenly_spaced_offsets,
        build_random_bursts,
        build_weighted_minute_loads,
        distribute_by_largest_remainder,
        partition_total_into_fixed_bursts,
        partition_total_into_bursts,
        same_model_streaks,
        weighted_choice,
        write_manifest,
    )


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
    use_system_message: bool = True


@dataclass(frozen=True)
class ExplicitScenario:
    scenario_name: str
    layout: str
    duration_ms: int
    total_requests: int
    seed: str
    archetype_keys: tuple[str, ...]
    model_counts: dict[str, int]
    output_relpath: Path
    minute_totals: tuple[int, ...] | None = None
    burst_size_range: tuple[int, int] | None = None
    preferred_burst_size: int | None = None
    slot_ms: int | None = None
    jitter_ms: int | None = None


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

LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Python")
DOMAINS = ("education", "energy", "retail", "climate", "transit", "health", "logistics", "agriculture")
PLACES = ("library", "harbor", "orchard", "bridge", "atrium", "greenhouse", "workshop", "station", "rooftop")
ROLES = ("analyst", "designer", "navigator", "coordinator", "operator", "planner", "editor", "reviewer")
TEAMS = ("studio team", "ops channel", "platform group", "customer desk", "service owners", "release crew")
SIGNALS = ("amber warning", "navy window", "jade queue", "teal marker", "silver incident tag", "cobalt fallback")
MATERIALS = ("basalt", "bamboo", "cedar", "copper", "glass", "granite", "linen", "clay", "steel")
ANIMALS = ("otter", "lynx", "heron", "ibis", "falcon", "lemur", "yak", "beetle", "orca", "stoat")
ISSUES = (
    "missing ownership",
    "conflicting rollout dates",
    "drifting latency",
    "flaky retries",
    "unclear rollback rules",
    "contradictory telemetry",
)
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
    raw = [archetype.base_count_60m * total_requests / base_total for archetype in archetypes]
    counts = distribute_by_largest_remainder(total_requests, raw)
    return {archetype.key: counts[idx] for idx, archetype in enumerate(archetypes)}


def resolve_counts(
    archetype_keys: tuple[str, ...],
    total_requests: int,
    counts_override: dict[str, int] | None = None,
) -> dict[str, int]:
    archetypes = tuple(ARCHETYPE_BY_KEY[key] for key in archetype_keys)
    if counts_override is None:
        return scaled_counts(total_requests, archetypes)
    counts = {key: 0 for key in archetype_keys}
    for key, value in counts_override.items():
        if key not in counts:
            raise ValueError(f"Unknown archetype key in counts_override: {key}")
        counts[key] = int(value)
    if sum(counts.values()) != total_requests:
        raise ValueError(f"counts_override totals {sum(counts.values())}, expected {total_requests}")
    return counts


def make_scenario(
    *,
    scenario_name: str,
    layout: str,
    duration_ms: int,
    total_requests: int,
    seed_suffix: str,
    output_relpath: Path,
    archetype_keys: tuple[str, ...],
    counts_override: dict[str, int] | None = None,
    minute_totals: tuple[int, ...] | None = None,
    burst_size_range: tuple[int, int] | None = None,
    preferred_burst_size: int | None = None,
    slot_ms: int | None = None,
    jitter_ms: int | None = None,
) -> ExplicitScenario:
    return ExplicitScenario(
        scenario_name=scenario_name,
        layout=layout,
        duration_ms=duration_ms,
        total_requests=total_requests,
        seed=f"{SEED}-{seed_suffix}",
        archetype_keys=archetype_keys,
        model_counts=resolve_counts(archetype_keys, total_requests, counts_override),
        output_relpath=output_relpath,
        minute_totals=minute_totals,
        burst_size_range=burst_size_range,
        preferred_burst_size=preferred_burst_size,
        slot_ms=slot_ms,
        jitter_ms=jitter_ms,
    )


SCENARIOS: tuple[ExplicitScenario, ...] = (
    make_scenario(
        scenario_name="10m_local5_skewed_bursty",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=TOTAL_REQUESTS["10m"],
        seed_suffix="10m",
        output_relpath=Path("10m") / "workload_explicit_local5_skewed_bursty_10m.csv",
        archetype_keys=("coder7", "coder14", "general7", "general14", "deepseek"),
    ),
    make_scenario(
        scenario_name="60m_local5_skewed_bursty",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["60m"],
        total_requests=TOTAL_REQUESTS["60m"],
        seed_suffix="60m",
        output_relpath=Path("60m") / "workload_explicit_local5_skewed_bursty_60m.csv",
        archetype_keys=("coder7", "coder14", "general7", "general14", "deepseek"),
    ),
    make_scenario(
        scenario_name="10m_local4_no_coder14_bursty_200",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=200,
        seed_suffix="10m-no-coder14-200",
        output_relpath=Path("10m") / "workload_explicit_local4_no_coder14_bursty_200_10m.csv",
        archetype_keys=("coder7", "general7", "general14", "deepseek"),
    ),
    make_scenario(
        scenario_name="10m_local2_mistral_deepseek_bursty_200",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=200,
        seed_suffix="10m-mistral-deepseek-200",
        output_relpath=Path("10m") / "workload_explicit_local2_mistral_deepseek_bursty_200_10m.csv",
        archetype_keys=("mistral7", "deepseek"),
    ),
    make_scenario(
        scenario_name="10m_local3_even_random_600",
        layout=LAYOUT_INTERLEAVED_RANDOM,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=600,
        seed_suffix="10m-local3-even-random-600",
        output_relpath=Path("10m") / "workload_explicit_local3_even_random_600_10m.csv",
        archetype_keys=("mistral7", "deepseek", "coder7"),
        counts_override={"mistral7": 200, "deepseek": 200, "coder7": 200},
    ),
    make_scenario(
        scenario_name="10m_local2_mistral_deepseek_bursty_600",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=600,
        seed_suffix="10m-mistral-deepseek-bursty-600",
        output_relpath=Path("10m") / "workload_explicit_local2_mistral_deepseek_bursty_600_10m.csv",
        archetype_keys=("mistral7", "deepseek"),
        counts_override={"mistral7": 319, "deepseek": 281},
        minute_totals=(42, 78, 54, 66, 48, 84, 54, 72, 48, 54),
        burst_size_range=(4, 12),
        preferred_burst_size=6,
    ),
    make_scenario(
        scenario_name="10m_local2_mistral_deepseek_bursty_2400",
        layout=LAYOUT_BURSTY,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=2400,
        seed_suffix="10m-mistral-deepseek-bursty-2400",
        output_relpath=Path("10m") / "workload_explicit_local2_mistral_deepseek_bursty_2400_10m.csv",
        archetype_keys=("mistral7", "deepseek"),
        counts_override={"mistral7": 1277, "deepseek": 1123},
        minute_totals=(168, 312, 216, 264, 192, 336, 216, 288, 192, 216),
        burst_size_range=(8, 24),
        preferred_burst_size=12,
    ),
    make_scenario(
        scenario_name="10m_local2_mistral_deepseek_even_jittered_600",
        layout=LAYOUT_EVEN_JITTERED,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=600,
        seed_suffix="10m-mistral-deepseek-even-jittered-600",
        output_relpath=Path("10m") / "workload_explicit_local2_mistral_deepseek_even_jittered_600_10m.csv",
        archetype_keys=("mistral7", "deepseek"),
        counts_override={"mistral7": 300, "deepseek": 300},
        minute_totals=(60, 60, 60, 60, 60, 60, 60, 60, 60, 60),
        slot_ms=1000,
        jitter_ms=250,
    ),
    make_scenario(
        scenario_name="10m_local2_mistral_deepseek_even_jittered_2400",
        layout=LAYOUT_EVEN_JITTERED,
        duration_ms=WINDOWS_MS["10m"],
        total_requests=2400,
        seed_suffix="10m-mistral-deepseek-even-jittered-2400",
        output_relpath=Path("10m") / "workload_explicit_local2_mistral_deepseek_even_jittered_2400_10m.csv",
        archetype_keys=("mistral7", "deepseek"),
        counts_override={"mistral7": 1200, "deepseek": 1200},
        minute_totals=(240, 240, 240, 240, 240, 240, 240, 240, 240, 240),
        slot_ms=250,
        jitter_ms=60,
    ),
)

SCENARIO_BY_NAME = {scenario.scenario_name: scenario for scenario in SCENARIOS}


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
        messages = [{"role": "user", "content": f"{system}\n\n{user}"}]
    return {
        "model": archetype.model_name,
        "stream": True,
        "max_tokens": rng.randint(*archetype.max_tokens_range),
        "temperature": round(rng.uniform(*archetype.temperature_range), 2),
        "messages": messages,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["request_id", "arrival_offset", "mode", "priority", "body_json"],
        )
        writer.writeheader()
        writer.writerows(rows)


def build_legacy_bursty_rows(
    scenario: ExplicitScenario,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
) -> list[dict[str, str]]:
    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    counters = {archetype.key: 0 for archetype in archetypes}
    bursts = build_random_bursts(
        scenario.model_counts,
        rng=rng,
        min_size=3,
        max_size=8,
    )
    minute_count = max(1, scenario.duration_ms // 60_000)
    per_minute_burst_counts = build_weighted_minute_loads(len(bursts), minute_count, rng)
    anchors = build_clustered_offsets(
        per_minute_counts=per_minute_burst_counts,
        duration_ms=scenario.duration_ms,
        rng=rng,
    )

    rows: list[dict[str, str]] = []
    for anchor, (key, burst_size) in zip(anchors, bursts, strict=True):
        archetype = archetype_by_key[key]
        offset = anchor
        for idx in range(burst_size):
            counters[key] += 1
            request_id = f"explicit-{key}-{counters[key]:04d}"
            if idx == 0:
                offset = min(anchor + rng.randint(0, 80), scenario.duration_ms - 1)
            else:
                step = rng.randint(25, 220 if idx < 3 else 950)
                offset = min(offset + step, scenario.duration_ms - 1)
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
    return rows

def build_interleaved_rows(
    scenario: ExplicitScenario,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
) -> list[dict[str, str]]:
    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    counters = {archetype.key: 0 for archetype in archetypes}
    sequence = build_balanced_sequence(scenario.model_counts, max_streak=2)
    minute_count = max(1, scenario.duration_ms // 60_000)
    per_minute = build_weighted_minute_loads(len(sequence), minute_count, rng)
    offsets = build_clustered_offsets(
        per_minute_counts=per_minute,
        duration_ms=scenario.duration_ms,
        rng=rng,
    )

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
    return rows


def distribute_model_counts_by_minute(
    model_counts: dict[str, int],
    minute_totals: tuple[int, ...],
) -> list[dict[str, int]]:
    keys = list(model_counts.keys())
    total_requests = sum(minute_totals)
    per_minute = [{key: 0 for key in keys} for _ in minute_totals]
    assigned_totals = [0] * len(minute_totals)

    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            minute_counts = [minute_totals[i] - assigned_totals[i] for i in range(len(minute_totals))]
        else:
            raw = [minute_total * model_counts[key] / total_requests for minute_total in minute_totals]
            minute_counts = distribute_by_largest_remainder(model_counts[key], raw)
        for minute_index, value in enumerate(minute_counts):
            per_minute[minute_index][key] = value
            assigned_totals[minute_index] += value
    return per_minute


def build_balanced_burst_sizes(
    minute_counts: dict[str, int],
    *,
    min_burst: int,
    max_burst: int,
    preferred_burst_size: int,
) -> dict[str, list[int]]:
    burst_counts = {
        key: len(
            partition_total_into_bursts(
                count,
                min_size=min_burst,
                max_size=max_burst,
                preferred_size=preferred_burst_size,
            )
        )
        for key, count in minute_counts.items()
        if count > 0
    }
    if len(burst_counts) == 2:
        ordered = sorted(burst_counts, key=lambda key: burst_counts[key], reverse=True)
        while burst_counts[ordered[0]] - burst_counts[ordered[1]] > 1:
            larger = ordered[0]
            smaller = ordered[1]
            larger_next = burst_counts[larger] - 1
            smaller_next = burst_counts[smaller] + 1
            can_reduce_larger = larger_next > 0 and min_burst <= (minute_counts[larger] / larger_next) <= max_burst
            can_grow_smaller = min_burst <= (minute_counts[smaller] / smaller_next) <= max_burst
            if can_reduce_larger:
                burst_counts[larger] = larger_next
            elif can_grow_smaller:
                burst_counts[smaller] = smaller_next
            else:
                break
            ordered = sorted(burst_counts, key=lambda key: burst_counts[key], reverse=True)
    return {
        key: partition_total_into_fixed_bursts(
            minute_counts[key],
            burst_count=burst_counts[key],
            min_size=min_burst,
            max_size=max_burst,
        )
        for key in burst_counts
    }


def build_minute_burst_starts(
    *,
    minute_index: int,
    burst_count: int,
    duration_ms: int,
    rng: random.Random,
) -> list[int]:
    if burst_count <= 0:
        return []
    minute_start = minute_index * 60_000
    slot_ms = 60_000 / burst_count
    jitter_ms = max(120, min(900, int(slot_ms * 0.18)))
    starts: list[int] = []
    for burst_index in range(burst_count):
        center = minute_start + int(slot_ms * burst_index + (slot_ms / 2))
        raw = center + rng.randint(-jitter_ms, jitter_ms)
        bounded = max(minute_start + 250, min(minute_start + 59_500, raw))
        starts.append(min(bounded, duration_ms - 1))
    starts.sort()
    return starts


def distribute_offsets_in_window(
    *,
    start_ms: int,
    end_ms: int,
    count: int,
    rng: random.Random,
) -> list[int]:
    if count <= 0:
        return []
    if count == 1:
        return [max(0, min(start_ms, end_ms))]

    usable_end = max(start_ms + count - 1, end_ms)
    span = usable_end - start_ms
    step = span / max(1, count - 1)
    offsets: list[int] = []
    for index in range(count):
        raw = start_ms + int(round(step * index))
        jitter = rng.randint(-max(1, int(step * 0.15)), max(1, int(step * 0.15)))
        bounded = raw + jitter
        lower_bound = start_ms if index == 0 else offsets[-1] + 1
        upper_bound = usable_end - (count - index - 1)
        offsets.append(max(lower_bound, min(upper_bound, bounded)))
    return offsets


def build_precise_bursty_rows(
    scenario: ExplicitScenario,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
) -> list[dict[str, str]]:
    if scenario.minute_totals is None or scenario.burst_size_range is None or scenario.preferred_burst_size is None:
        raise ValueError(f"{scenario.scenario_name} requires minute_totals, burst_size_range, and preferred_burst_size")

    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    counters = {archetype.key: 0 for archetype in archetypes}
    minute_model_counts = distribute_model_counts_by_minute(scenario.model_counts, scenario.minute_totals)
    min_burst, max_burst = scenario.burst_size_range

    rows: list[dict[str, str]] = []
    previous_last_model: str | None = None

    for minute_index, minute_counts in enumerate(minute_model_counts):
        burst_sizes_by_model = build_balanced_burst_sizes(
            minute_counts,
            min_burst=min_burst,
            max_burst=max_burst,
            preferred_burst_size=scenario.preferred_burst_size,
        )
        burst_sequence = build_balanced_sequence(
            {key: len(parts) for key, parts in burst_sizes_by_model.items()},
            max_streak=1,
            avoid_first_key=previous_last_model,
        )
        burst_starts = build_minute_burst_starts(
            minute_index=minute_index,
            burst_count=len(burst_sequence),
            duration_ms=scenario.duration_ms,
            rng=rng,
        )
        burst_queues = {key: list(parts) for key, parts in burst_sizes_by_model.items()}
        minute_start = minute_index * 60_000

        for burst_index, (model_key, burst_start) in enumerate(zip(burst_sequence, burst_starts, strict=True)):
            burst_size = burst_queues[model_key].pop(0)
            next_start = burst_starts[burst_index + 1] if burst_index + 1 < len(burst_starts) else minute_start + 59_500
            min_gap = 240 if scenario.total_requests <= 600 else 140
            max_span = 1_800 if scenario.total_requests <= 600 else 2_200
            burst_end = min(next_start - min_gap, burst_start + max_span)
            burst_end = max(burst_start + burst_size - 1, burst_end)
            offsets = distribute_offsets_in_window(
                start_ms=burst_start,
                end_ms=min(burst_end, scenario.duration_ms - 1),
                count=burst_size,
                rng=rng,
            )
            archetype = archetype_by_key[model_key]
            for offset in offsets:
                counters[model_key] += 1
                request_id = f"explicit-{model_key}-{counters[model_key]:04d}"
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

        previous_last_model = burst_sequence[-1] if burst_sequence else previous_last_model

    rows.sort(key=lambda row: (float(row["arrival_offset"]), row["request_id"]))
    streaks = same_model_streaks([json.loads(row["body_json"])["model"] for row in rows])
    if any(size in (1, 2) for _, size in streaks):
        raise ValueError(f"{scenario.scenario_name} generated a singleton or two-request burst")
    return rows


def build_even_jittered_rows(
    scenario: ExplicitScenario,
    archetypes: tuple[Archetype, ...],
    rng: random.Random,
) -> list[dict[str, str]]:
    if scenario.minute_totals is None or scenario.slot_ms is None or scenario.jitter_ms is None:
        raise ValueError(f"{scenario.scenario_name} requires minute_totals, slot_ms, and jitter_ms")

    archetype_by_key = {archetype.key: archetype for archetype in archetypes}
    counters = {archetype.key: 0 for archetype in archetypes}
    minute_model_counts = distribute_model_counts_by_minute(scenario.model_counts, scenario.minute_totals)

    rows: list[dict[str, str]] = []
    previous_last_key: str | None = None
    for minute_index, minute_total in enumerate(scenario.minute_totals):
        minute_counts = minute_model_counts[minute_index]
        sequence = build_balanced_sequence(
            minute_counts,
            max_streak=1,
            avoid_first_key=previous_last_key,
        )
        offsets = build_evenly_spaced_offsets(
            minute_index=minute_index,
            count=minute_total,
            slot_ms=scenario.slot_ms,
            jitter_ms=scenario.jitter_ms,
            rng=rng,
            duration_ms=scenario.duration_ms,
        )
        for offset, model_key in zip(offsets, sequence, strict=True):
            archetype = archetype_by_key[model_key]
            counters[model_key] += 1
            request_id = f"explicit-{model_key}-{counters[model_key]:04d}"
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
        previous_last_key = sequence[-1] if sequence else previous_last_key

    rows.sort(key=lambda row: (float(row["arrival_offset"]), row["request_id"]))
    return rows


def render_scenario_manifest(scenario: ExplicitScenario) -> ScenarioManifest:
    return ScenarioManifest(
        scenario_name=scenario.scenario_name,
        layout=scenario.layout,
        duration_ms=scenario.duration_ms,
        total_requests=scenario.total_requests,
        seed=scenario.seed,
        model_counts={
            ARCHETYPE_BY_KEY[key].model_name: scenario.model_counts[key]
            for key in scenario.archetype_keys
            if scenario.model_counts.get(key, 0) > 0
        },
        minute_totals=list(scenario.minute_totals) if scenario.minute_totals is not None else None,
        burst_size_range=list(scenario.burst_size_range) if scenario.burst_size_range is not None else None,
        slot_ms=scenario.slot_ms,
        jitter_ms=scenario.jitter_ms,
        output_csv=str(scenario.output_relpath),
    )


def build_rows_for_scenario(scenario: ExplicitScenario) -> list[dict[str, str]]:
    rng = random.Random(scenario.seed)
    archetypes = tuple(ARCHETYPE_BY_KEY[key] for key in scenario.archetype_keys)
    if scenario.layout == LAYOUT_INTERLEAVED_RANDOM:
        rows = build_interleaved_rows(scenario, archetypes, rng)
    elif scenario.layout == LAYOUT_EVEN_JITTERED:
        rows = build_even_jittered_rows(scenario, archetypes, rng)
    elif scenario.minute_totals is not None and scenario.burst_size_range is not None:
        rows = build_precise_bursty_rows(scenario, archetypes, rng)
    else:
        rows = build_legacy_bursty_rows(scenario, archetypes, rng)

    if len(rows) != scenario.total_requests:
        raise ValueError(f"{scenario.scenario_name}: expected {scenario.total_requests} rows, built {len(rows)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate direct-model benchmark workloads.")
    parser.add_argument(
        "--root",
        default="tests/performance/workloads/explicit",
        help="Root directory for generated workload folders.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Generate only the named scenario. Repeat to generate multiple scenarios.",
    )
    args = parser.parse_args()

    requested = set(args.scenario or [])
    unknown = requested - set(SCENARIO_BY_NAME)
    if unknown:
        parser.error(f"Unknown scenario name(s): {', '.join(sorted(unknown))}")

    root = Path(args.root)
    selected = [scenario for scenario in SCENARIOS if not requested or scenario.scenario_name in requested]
    for scenario in selected:
        rows = build_rows_for_scenario(scenario)
        output_path = root / scenario.output_relpath
        write_csv(output_path, rows)
        write_manifest(output_path.with_suffix(".json"), render_scenario_manifest(scenario))
        print(f"Wrote {len(rows)} requests to {output_path}")

    print("Scenario distributions:")
    for scenario in selected:
        print(f"  {scenario.scenario_name}: {scenario.model_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
