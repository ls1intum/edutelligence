"""Generate coder dual-model workloads for explicit scheduling benchmarks.

Three scenarios targeting only the 7B and 14B coder models:

  coder2_big_bursty_600  —  600 requests / 10 min, alternating large same-model
                            bursts of 20–40 requests with clear gaps between them.
  coder2_big_bursty_2400 — 2400 requests / 10 min, same burst pattern but denser
                            (50–100 per burst, tight intra-burst spacing).
  coder2_fully_random_600 — 600 requests / 10 min, Poisson arrivals with a fully
                             random 50/50 model split.

Run:
    python tests/performance/generate_coder_dual_model_workloads.py

Output lands under tests/performance/workloads/explicit/10m/.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


SEED = 20260407
DURATION_MS = 10 * 60 * 1000  # 10 minutes


@dataclass(frozen=True)
class Archetype:
    key: str
    model_name: str
    prompts: tuple[str, ...]
    max_tokens_range: tuple[int, int]
    temperature_range: tuple[float, float]
    interactive_weight: float
    high_priority_weight: float
    mid_priority_weight: float
    use_system_message: bool = True


# ---------------------------------------------------------------------------
# Archetype definitions — fresh prompts, not reused from other generators
# ---------------------------------------------------------------------------

CODER7 = Archetype(
    key="coder7",
    model_name="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
    prompts=(
        "Fix a {language} off-by-one error in a {team} pagination helper; add one focused unit test.",
        "Simplify a tangled {language} retry loop in {place}; remove dead branches and add an early-exit guard.",
        "Patch a {language} config loader for {domain} that silently ignores malformed {signal} values; add a validation step.",
        "Rename a confusing {language} variable in a {team} caching module where {issue} led to a naming collision.",
        "Write a concise {language} test fixture for a {domain} rate-limiter that uses {signal} as a test trigger.",
        "Extract a duplicated {language} timestamp parser shared by {module_a} and {module_b} into a single utility.",
        "Remove a commented-out {language} block left by {team} after {issue}; update the surrounding docstring.",
        "Harden a {language} env-var reader for {domain}: raise early if required keys are absent rather than defaulting silently.",
        "Add a missing null-guard to a {language} {place} event handler that panics when {material} input is empty.",
        "Rewrite a brittle {language} boolean flag in a {team} circuit-breaker using an explicit state enum.",
        "Shrink a {language} log statement in the {module_a} path that serialises the full {signal} object; log only the key field.",
        "Swap a raw {language} dict literal in a {domain} config for a typed dataclass; keep the wire format identical.",
    ),
    max_tokens_range=(160, 260),
    temperature_range=(0.05, 0.25),
    interactive_weight=0.82,
    high_priority_weight=0.28,
    mid_priority_weight=0.54,
)

CODER14 = Archetype(
    key="coder14",
    model_name="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    prompts=(
        "Trace a {language} memory leak through {module_a}, {module_b}, and {module_c} in a {domain} pipeline; propose the safest fix and its rollback.",
        "Design a migration path for a {team} {language} service moving from per-request {signal} locks to a shared connection pool; discuss tradeoffs.",
        "Evaluate two competing approaches for handling {issue} in a {language} {domain} job scheduler; recommend one with concrete reasoning.",
        "Audit a {language} API boundary in {place} where {material} encoding assumptions differ between caller and callee; draft a compatibility shim.",
        "Reason through a {language} distributed-cache invalidation bug in {domain} where {signal} races with a background refresh; propose a fix and invariant.",
        "Compare eager versus lazy loading strategies for a {language} {team} service given {issue}; outline the schema migration for each.",
        "Analyse a {language} retry storm in {module_a} triggered when {signal} spikes; explain the backpressure mechanism and propose two remediation levels.",
        "Review a {language} multi-tenant isolation boundary in {domain} where {issue} allowed {role} to access a neighbouring tenant's {material} store.",
        "Propose a rollout strategy for a {language} breaking change in {module_a} that {module_b} and {module_c} depend on; include a feature-flag plan.",
        "Diagnose a {language} O(n²) scan in a {domain} hot path caused by {issue}; recommend the correct data structure and an incremental migration.",
        "Explain why a {language} {team} deployment health check passes while {signal} shows elevated error rates; identify the detection gap and fix it.",
        "Model the failure modes of a {language} pipeline in {place} where {module_a} can silently drop events if {material} exceeds a threshold.",
    ),
    max_tokens_range=(220, 420),
    temperature_range=(0.05, 0.20),
    interactive_weight=0.74,
    high_priority_weight=0.42,
    mid_priority_weight=0.41,
)

ARCHETYPES: tuple[Archetype, ...] = (CODER7, CODER14)
ARCHETYPE_BY_KEY = {a.key: a for a in ARCHETYPES}

# ---------------------------------------------------------------------------
# Slot vocabulary (same as the main generator for consistency)
# ---------------------------------------------------------------------------

LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Go", "Rust")
DOMAINS = ("education", "energy", "retail", "climate", "transit", "health", "logistics", "agriculture")
PLACES = ("library", "harbor", "orchard", "bridge", "atrium", "greenhouse", "workshop", "station", "rooftop")
ROLES = ("analyst", "designer", "navigator", "coordinator", "operator", "planner", "editor", "reviewer")
TEAMS = ("studio team", "ops channel", "platform group", "customer desk", "service owners", "release crew")
SIGNALS = ("amber warning", "navy window", "jade queue", "teal marker", "silver incident tag", "cobalt fallback")
MATERIALS = ("basalt", "bamboo", "cedar", "copper", "glass", "granite", "linen", "clay", "steel")
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

# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

VARIANTS: tuple[dict, ...] = (
    {
        "name": "coder2_big_bursty_600",
        "total_requests": 600,
        "counts_override": {"coder7": 300, "coder14": 300},
        "seed_suffix": "coder2-big-bursty-600",
        "layout": "big_bursty",
        "burst_min": 20,
        "burst_max": 40,
        "intra_step_ms": (150, 600),
        "output_relpath": Path("10m") / "workload_coder2_big_bursty_600_10m.csv",
    },
    {
        "name": "coder2_big_bursty_2400",
        "total_requests": 2400,
        "counts_override": {"coder7": 1200, "coder14": 1200},
        "seed_suffix": "coder2-big-bursty-2400",
        "layout": "big_bursty",
        "burst_min": 50,
        "burst_max": 100,
        "intra_step_ms": (50, 200),
        "output_relpath": Path("10m") / "workload_coder2_big_bursty_2400_10m.csv",
    },
    {
        "name": "coder2_fully_random_600",
        "total_requests": 600,
        "counts_override": {"coder7": 300, "coder14": 300},
        "seed_suffix": "coder2-fully-random-600",
        "layout": "fully_random",
        "output_relpath": Path("10m") / "workload_coder2_fully_random_600_10m.csv",
    },
)


# ---------------------------------------------------------------------------
# Priority / mode helpers
# ---------------------------------------------------------------------------

def choose_priority(archetype: Archetype, rng: random.Random) -> str:
    if rng.random() < archetype.high_priority_weight:
        return "high"
    remaining_weight = 1.0 - archetype.high_priority_weight
    if rng.random() < archetype.mid_priority_weight / max(1e-9, remaining_weight):
        return "mid"
    return "low"


def choose_mode(archetype: Archetype, rng: random.Random) -> str:
    return "interactive" if rng.random() < archetype.interactive_weight else "batch"


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def build_payload(archetype: Archetype, rng: random.Random) -> dict:
    language = rng.choice(LANGUAGES)
    domain = rng.choice(DOMAINS)
    place = rng.choice(PLACES)
    role = rng.choice(ROLES)
    team = rng.choice(TEAMS)
    signal = rng.choice(SIGNALS)
    material = rng.choice(MATERIALS)
    issue = rng.choice(ISSUES)
    module_a, module_b, module_c = rng.choice(MODULES)

    system = "Follow the user instructions exactly. Keep the answer concise unless the task clearly needs detail."
    user = rng.choice(archetype.prompts).format(
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


# ---------------------------------------------------------------------------
# Big-bursty layout
# ---------------------------------------------------------------------------

def build_big_bursts(
    counts: dict[str, int],
    rng: random.Random,
    *,
    burst_min: int,
    burst_max: int,
) -> list[tuple[str, int]]:
    """Alternate between the two models in large same-model bursts.

    Burst sizes are drawn from [burst_min, burst_max].  Tiny tails (fewer than
    burst_min // 2 remaining) are absorbed into the preceding burst so the
    workload ends cleanly without degenerate 1- or 2-request clusters.
    """
    remaining = dict(counts)
    keys = [k for k in counts]  # preserve insertion order
    key_idx = 0
    bursts: list[tuple[str, int]] = []

    while sum(remaining.values()) > 0:
        # Advance to the next non-exhausted model (round-robin)
        for _ in range(len(keys)):
            key = keys[key_idx % len(keys)]
            key_idx += 1
            if remaining.get(key, 0) > 0:
                break
        else:
            break  # all exhausted

        available = remaining[key]
        if available <= burst_min:
            size = available
        else:
            size = min(available, rng.randint(burst_min, burst_max))
            # absorb a tiny tail so we don't leave a stub burst
            tail = available - size
            if 0 < tail < burst_min // 2:
                size = available

        bursts.append((key, size))
        remaining[key] -= size

    return bursts


def build_big_burst_anchors(
    duration_ms: int,
    burst_count: int,
    rng: random.Random,
) -> list[int]:
    """Slot-based anchor placement with clear inter-burst gaps.

    Divides the window into *burst_count* equal slots and picks a random start
    point within the first 60 % of each slot.  The remaining 40 % of each slot
    forms the gap before the next burst begins.
    """
    slot_ms = duration_ms // max(burst_count, 1)
    anchors: list[int] = []
    for i in range(burst_count):
        slot_start = i * slot_ms
        max_anchor = min(slot_start + int(slot_ms * 0.60), duration_ms - 1)
        anchors.append(rng.randint(slot_start, max(slot_start, max_anchor)))
    return sorted(anchors)


def build_big_bursty_rows(
    duration_ms: int,
    total_requests: int,
    rng: random.Random,
    *,
    counts: dict[str, int],
    burst_min: int,
    burst_max: int,
    intra_step_ms: tuple[int, int],
) -> list[dict[str, str]]:
    """Build rows with large same-model bursts separated by visible gaps."""
    bursts = build_big_bursts(counts, rng, burst_min=burst_min, burst_max=burst_max)
    anchors = build_big_burst_anchors(duration_ms, len(bursts), rng)
    counters: dict[str, int] = {k: 0 for k in counts}
    rows: list[dict[str, str]] = []

    for anchor, (key, burst_size) in zip(anchors, bursts):
        archetype = ARCHETYPE_BY_KEY[key]
        offset = anchor
        for idx in range(burst_size):
            counters[key] += 1
            request_id = f"coder-{key}-{counters[key]:04d}"
            if idx == 0:
                offset = min(anchor + rng.randint(0, 100), duration_ms - 1)
            else:
                step = rng.randint(*intra_step_ms)
                offset = min(offset + step, duration_ms - 1)
            payload = build_payload(archetype, rng)
            rows.append({
                "request_id": request_id,
                "arrival_offset": str(offset),
                "mode": choose_mode(archetype, rng),
                "priority": choose_priority(archetype, rng),
                "body_json": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            })

    rows.sort(key=lambda r: (float(r["arrival_offset"]), r["request_id"]))
    if len(rows) != total_requests:
        raise ValueError(f"Expected {total_requests} rows, built {len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# Fully-random layout (Poisson arrivals)
# ---------------------------------------------------------------------------

def build_poisson_offsets(
    duration_ms: int,
    total_requests: int,
    rng: random.Random,
) -> list[int]:
    """Exponential (memoryless) inter-arrival times, capped to the window."""
    mean_gap_ms = duration_ms / total_requests
    offsets: list[int] = []
    t = 0.0
    for _ in range(total_requests):
        # Exponential inter-arrival: -mean * ln(U), U ~ Uniform(0, 1)
        t += -mean_gap_ms * math.log(max(rng.random(), 1e-12))
        offsets.append(min(int(t), duration_ms - 1))
    return sorted(offsets)


def build_fully_random_rows(
    duration_ms: int,
    total_requests: int,
    rng: random.Random,
    *,
    counts: dict[str, int],
) -> list[dict[str, str]]:
    """Poisson arrivals, shuffled 50/50 model split, fully random prompts."""
    offsets = build_poisson_offsets(duration_ms, total_requests, rng)

    # Build a shuffled model sequence with exact per-model counts
    sequence: list[str] = []
    for key, count in counts.items():
        sequence.extend([key] * count)
    rng.shuffle(sequence)

    counters: dict[str, int] = {k: 0 for k in counts}
    rows: list[dict[str, str]] = []

    for offset, key in zip(offsets, sequence):
        archetype = ARCHETYPE_BY_KEY[key]
        counters[key] += 1
        request_id = f"coder-{key}-{counters[key]:04d}"
        payload = build_payload(archetype, rng)
        rows.append({
            "request_id": request_id,
            "arrival_offset": str(offset),
            "mode": choose_mode(archetype, rng),
            "priority": choose_priority(archetype, rng),
            "body_json": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        })

    rows.sort(key=lambda r: (float(r["arrival_offset"]), r["request_id"]))
    if len(rows) != total_requests:
        raise ValueError(f"Expected {total_requests} rows, built {len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["request_id", "arrival_offset", "mode", "priority", "body_json"],
        )
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate coder dual-model benchmark workloads (7B + 14B).",
    )
    parser.add_argument(
        "--root",
        default="tests/performance/workloads/explicit",
        help="Root directory for generated workload folders.",
    )
    args = parser.parse_args()
    root = Path(args.root)

    for variant in VARIANTS:
        counts: dict[str, int] = dict(variant["counts_override"])
        rng = random.Random(f"{SEED}-{variant['seed_suffix']}")
        layout: str = variant["layout"]

        if layout == "big_bursty":
            rows = build_big_bursty_rows(
                DURATION_MS,
                variant["total_requests"],
                rng,
                counts=counts,
                burst_min=variant["burst_min"],
                burst_max=variant["burst_max"],
                intra_step_ms=variant["intra_step_ms"],
            )
        elif layout == "fully_random":
            rows = build_fully_random_rows(
                DURATION_MS,
                variant["total_requests"],
                rng,
                counts=counts,
            )
        else:
            raise ValueError(f"Unknown layout: {layout!r}")

        output_path = root / variant["output_relpath"]
        write_csv(output_path, rows)
        print(f"Wrote {len(rows):>5} requests  →  {output_path}")

    print("\nModel distribution per scenario:")
    for variant in VARIANTS:
        print(f"  {variant['name']}:")
        for key, count in variant["counts_override"].items():
            print(f"    {key}: {count}  ({ARCHETYPE_BY_KEY[key].model_name})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
