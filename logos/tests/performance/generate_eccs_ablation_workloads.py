"""Generate resource-mode workloads for ECCS ablation benchmarks.

Creates workloads where classification routes to DIFFERENT models based on
prompt type, enabling meaningful ECCS correction measurements:

  - code_quick  → system tags match Coder-7B  (fast coding, debugging)
  - reason_deep → system tags match Coder-14B (architecture, math, reasoning)
  - general     → system tags match Mistral-7B (chat, writing, summarization)

The system prompt for each archetype contains keywords that match the
model's ``tags`` field in the DB, driving the TokenClassifier (weight 1.9)
to favor the intended model.  No ``model`` field is set — classification
+ ECCS decide.

Usage:
    python3 tests/performance/generate_eccs_ablation_workloads.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


SEED = 20260412


@dataclass(frozen=True)
class Archetype:
    key: str
    system_prompt: str
    prompts: tuple[str, ...]
    max_tokens_range: tuple[int, int]
    temperature_range: tuple[float, float]
    interactive_weight: float
    high_priority_weight: float
    mid_priority_weight: float


# ── Archetypes ──────────────────────────────────────────────────────
#
# System prompts contain tag keywords that match the DB tags:
#   Coder-7B:  coding code python typescript debugging refactor tests fast efficient
#   Coder-14B: coding code architecture reasoning complex analysis math debugging deep
#   Mistral:   chat writing summarize general instruction conversation creative qa knowledge

ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        key="code_quick",
        # Tags: coding, code, python, debugging, efficient, fast, refactor, tests
        # Matches Coder-7B: 8/9, Coder-14B: 3/9, Mistral: 0/9
        system_prompt=(
            "Prefer coding code python debugging efficient fast refactor tests. "
            "Keep the answer patch-focused and compact."
        ),
        prompts=(
            "Patch a small {language} handler used by {team}; keep the diff short and add a focused regression test.",
            "Debug a compact {language} endpoint in {place} where {signal} exposes a brittle edge; stay implementation-first.",
            "Repair a tiny {language} utility after a {material} mismatch caused {issue}; prefer the smallest safe change.",
            "Tighten a short {language} parser for {team}; remove the flaky branch around {signal} and call out one test to add.",
            "Refactor a lightweight {language} helper for {domain} after {issue}; propose the minimal safe fix and quick validation.",
            "Fix a {language} function that silently drops {signal} events in {place}; add a guard and one assertion.",
        ),
        max_tokens_range=(140, 260),
        temperature_range=(0.05, 0.25),
        interactive_weight=0.82,
        high_priority_weight=0.28,
        mid_priority_weight=0.54,
    ),
    Archetype(
        key="reason_deep",
        # Tags: architecture, reasoning, complex, analysis, math, deep
        # Matches Coder-14B: 6/9, Coder-7B: 0/9, Mistral: 0/9
        system_prompt=(
            "Prefer architecture reasoning complex analysis math deep. "
            "Show structured reasoning and justify tradeoffs."
        ),
        prompts=(
            "Diagnose a complex {language} scheduling regression across {module_a}, {module_b}, and {module_c}; explain the safest rollout.",
            "Compare two backend designs for a {domain} service after {signal} exposed hidden coupling; recommend one with rationale.",
            "Audit an architecture change for {team} where {issue} spans several layers; propose a staged migration plan.",
            "Reason through a deep concurrency failure in a {language} service for {domain}; contrast the top two fixes.",
            "Analyze why queue growth in {place} contradicts the telemetry after {animal} was marked healthy; defend the best explanation.",
            "Solve a prioritization problem for {domain} involving {signal}, delayed ownership, and one hard constraint; show the decision path.",
        ),
        max_tokens_range=(200, 380),
        temperature_range=(0.05, 0.20),
        interactive_weight=0.74,
        high_priority_weight=0.42,
        mid_priority_weight=0.41,
    ),
    Archetype(
        key="general",
        # Tags: chat, writing, summarize, general, instruction, creative
        # Matches Mistral: 6/9, Coder-7B: 0/9, Coder-14B: 0/9
        system_prompt=(
            "Prefer chat writing summarize general instruction creative. "
            "Keep replies practical and brief."
        ),
        prompts=(
            "Rewrite a messy handoff for {team} into a short customer-ready update that mentions {signal} and one next step.",
            "Summarize a brief incident note from {place} involving {material} and {animal}; keep it tight and actionable.",
            "Convert a rough project note for {domain} into three crisp bullets without changing the meaning.",
            "Draft a compact support reply for {role} about {issue}; keep the tone practical and brief.",
            "Condense a noisy status thread from {team} into a direct handoff with one action item.",
            "Write a quick overview of {domain} developments in {place} for {role}; focus on what changed and one next step.",
        ),
        max_tokens_range=(100, 220),
        temperature_range=(0.10, 0.35),
        interactive_weight=0.88,
        high_priority_weight=0.18,
        mid_priority_weight=0.61,
    ),
)

ARCHETYPE_BY_KEY = {a.key: a for a in ARCHETYPES}

LANGUAGES = ("Python", "TypeScript", "Python", "TypeScript", "Python")
DOMAINS = ("education", "energy", "retail", "climate", "transit", "health", "logistics")
PLACES = ("library", "harbor", "orchard", "bridge", "atrium", "workshop", "station")
ROLES = ("analyst", "designer", "coordinator", "operator", "planner", "reviewer")
TEAMS = ("studio team", "ops channel", "platform group", "service owners", "release crew")
SIGNALS = ("amber warning", "jade queue", "teal marker", "silver incident tag", "cobalt fallback")
MATERIALS = ("basalt", "bamboo", "cedar", "copper", "glass", "granite", "linen")
ANIMALS = ("otter", "lynx", "heron", "falcon", "lemur", "beetle", "orca")
ISSUES = ("missing ownership", "drifting latency", "flaky retries", "contradictory telemetry", "unclear rollback rules")
MODULES = (
    ("queue", "planner", "executor"),
    ("scheduler", "monitor", "recorder"),
    ("policy engine", "resolver", "executor"),
    ("router", "queue", "billing"),
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
            {"role": "system", "content": archetype.system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }


def _build_random_offsets(
    duration_ms: int, total_requests: int, rng: random.Random,
) -> list[int]:
    """Distribute requests across the time window with mild clustering."""
    minute_count = max(1, duration_ms // 60_000)
    weights = []
    for minute in range(minute_count):
        wave = 0.8 + 0.5 * (1.0 + math.sin(
            (minute / max(1, minute_count)) * math.tau * 2.2 + 0.4
        ))
        burst = rng.choice((0.65, 0.85, 1.0, 1.15, 1.35, 1.8, 2.4))
        weights.append(wave * burst * rng.uniform(0.75, 1.35))

    scaled = [total_requests * w / sum(weights) for w in weights]
    per_minute = [int(v) for v in scaled]
    remainder = total_requests - sum(per_minute)
    ranked = sorted(enumerate(scaled), key=lambda x: x[1] - int(x[1]), reverse=True)
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
            offsets.append(min(
                duration_ms - 1,
                minute * 60_000 + int(seconds * 1000) + rng.randint(0, 250),
            ))

    offsets.sort()
    return offsets


def _build_interleaved_sequence(
    counts: dict[str, int], rng: random.Random,
) -> list[str]:
    """Build a random interleaved sequence avoiding >2 consecutive same-type."""
    remaining = dict(counts)
    sequence: list[str] = []
    while sum(remaining.values()) > 0:
        candidates = [
            (k, float(v))
            for k, v in remaining.items()
            if v > 0 and not (
                len(sequence) >= 2
                and sequence[-1] == k
                and sequence[-2] == k
            )
        ]
        if not candidates:
            candidates = [(k, float(v)) for k, v in remaining.items() if v > 0]
        total = sum(w for _, w in candidates)
        needle = rng.random() * total
        running = 0.0
        chosen = candidates[-1][0]
        for k, w in candidates:
            running += w
            if needle <= running:
                chosen = k
                break
        sequence.append(chosen)
        remaining[chosen] -= 1
    return sequence


def build_workload(total_requests: int, seed_suffix: str) -> list[dict[str, str]]:
    """Build a resource-mode workload with even 3-way archetype split."""
    rng = random.Random(f"{SEED}-{seed_suffix}")
    duration_ms = 10 * 60 * 1000  # 10 minutes

    per_archetype = total_requests // 3
    remainder = total_requests % 3
    counts = {
        "code_quick": per_archetype + (1 if remainder > 0 else 0),
        "reason_deep": per_archetype + (1 if remainder > 1 else 0),
        "general": per_archetype,
    }

    # Interleaved archetype sequence
    sequence = _build_interleaved_sequence(counts, rng)
    # Random time offsets
    offsets = _build_random_offsets(duration_ms, total_requests, rng)

    counters: dict[str, int] = {k: 0 for k in counts}
    rows = []
    for offset_ms, arch_key in zip(offsets, sequence):
        archetype = ARCHETYPE_BY_KEY[arch_key]
        counters[arch_key] += 1
        request_id = f"eccs-{arch_key}-{counters[arch_key]:04d}"
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

    for total in (150, 300, 600):
        rows = build_workload(total, seed_suffix=f"hw3-eccs-{total}")
        path = root / f"workload_eccs_hw3_even_random_{total}_10m.csv"
        write_csv(path, rows)

        # Count archetypes
        from collections import Counter
        arch_counts = Counter()
        for r in rows:
            arch_counts[r["request_id"].split("-")[1]] += 1

        print(f"Wrote {len(rows):>4d} requests to {path}")
        print(f"       Archetypes: {dict(arch_counts)}")

        # Arrival distribution
        offsets = [int(r["arrival_offset"]) for r in rows]
        print(f"       Span: {offsets[0]/1000:.1f}s - {offsets[-1]/1000:.1f}s")
        for minute in range(10):
            lo, hi = minute * 60000, (minute + 1) * 60000
            c = sum(1 for o in offsets if lo <= o < hi)
            bar = "#" * (c // 2)
            print(f"         {minute}-{minute+1}min: {c:>3d} {bar}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
