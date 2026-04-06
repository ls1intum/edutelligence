"""Shared workload layout helpers for performance benchmark generators."""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


LAYOUT_BURSTY = "bursty"
LAYOUT_EVEN_JITTERED = "even_jittered"
LAYOUT_INTERLEAVED_RANDOM = "interleaved_random"


@dataclass(frozen=True)
class ScenarioManifest:
    scenario_name: str
    layout: str
    duration_ms: int
    total_requests: int
    seed: str
    model_counts: dict[str, int]
    minute_totals: list[int] | None = None
    burst_size_range: list[int] | None = None
    slot_ms: int | None = None
    jitter_ms: int | None = None
    output_csv: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


def write_manifest(path: Path, manifest: ScenarioManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def weighted_choice(rng: random.Random, weighted_keys: Sequence[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in weighted_keys)
    if total <= 0:
        raise ValueError("weighted_choice requires a positive total weight")
    needle = rng.random() * total
    running = 0.0
    for key, weight in weighted_keys:
        running += weight
        if needle <= running:
            return key
    return weighted_keys[-1][0]


def distribute_by_largest_remainder(total: int, raw_values: Sequence[float]) -> list[int]:
    counts = [int(math.floor(value)) for value in raw_values]
    remainder = total - sum(counts)
    ranked = sorted(
        range(len(raw_values)),
        key=lambda idx: (raw_values[idx] - counts[idx], raw_values[idx], -idx),
        reverse=True,
    )
    for idx in ranked[:remainder]:
        counts[idx] += 1
    return counts


def build_weighted_minute_loads(total: int, minute_count: int, rng: random.Random) -> list[int]:
    weights: list[float] = []
    for minute in range(minute_count):
        wave = 0.8 + 0.45 * (1.0 + math.sin((minute / max(1, minute_count)) * math.tau * 3.0 + 0.8))
        burst = rng.choice((0.65, 0.75, 0.9, 1.0, 1.25, 1.6, 2.1, 2.8))
        weights.append(wave * burst * rng.uniform(0.75, 1.35))
    scaled = [total * weight / sum(weights) for weight in weights]
    return distribute_by_largest_remainder(total, scaled)


def build_clustered_offsets_for_minute(
    *,
    minute_index: int,
    count: int,
    duration_ms: int,
    rng: random.Random,
) -> list[int]:
    if count <= 0:
        return []

    cluster_count = min(count, rng.choice((1, 1, 2, 2, 3, 4)))
    centers = sorted(rng.uniform(2.0, 57.5) for _ in range(cluster_count))
    offsets: list[int] = []
    for _ in range(count):
        center = rng.choice(centers)
        seconds = max(0.0, min(59.95, rng.gauss(center, rng.uniform(0.45, 3.8))))
        milliseconds = minute_index * 60_000 + int(seconds * 1000) + rng.randint(0, 999)
        offsets.append(min(milliseconds, duration_ms - 1))
    offsets.sort()
    return offsets


def build_clustered_offsets(
    *,
    per_minute_counts: Sequence[int],
    duration_ms: int,
    rng: random.Random,
) -> list[int]:
    offsets: list[int] = []
    for minute_index, count in enumerate(per_minute_counts):
        offsets.extend(
            build_clustered_offsets_for_minute(
                minute_index=minute_index,
                count=count,
                duration_ms=duration_ms,
                rng=rng,
            )
        )
    offsets.sort()
    return offsets


def choose_burst_count(total: int, min_size: int, max_size: int, preferred_size: int) -> int:
    if total <= 0:
        return 0
    min_bursts = math.ceil(total / max_size)
    max_bursts = max(1, total // min_size)
    target = max(1, round(total / preferred_size))
    return min(max(target, min_bursts), max_bursts)


def build_random_bursts(
    counts: Mapping[str, int],
    *,
    rng: random.Random,
    min_size: int,
    max_size: int,
) -> list[tuple[str, int]]:
    remaining = {key: int(value) for key, value in counts.items()}
    bursts: list[tuple[str, int]] = []
    while sum(remaining.values()) > 0:
        candidates = [(key, float(value)) for key, value in remaining.items() if value > 0]
        key = weighted_choice(rng, candidates)
        remaining_for_key = remaining[key]
        if remaining_for_key <= min_size:
            burst_size = remaining_for_key
        else:
            burst_size = min(remaining_for_key, rng.randint(min_size, max_size))
            if remaining_for_key - burst_size in (1, 2):
                burst_size -= 1 if burst_size > min_size else 0
        bursts.append((key, burst_size))
        remaining[key] -= burst_size
    return bursts


def partition_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    base = total // bucket_count
    remainder = total % bucket_count
    parts = [base + 1] * remainder + [base] * (bucket_count - remainder)
    return parts


def partition_total_into_fixed_bursts(
    total: int,
    *,
    burst_count: int,
    min_size: int,
    max_size: int,
) -> list[int]:
    if total <= 0:
        return []
    parts = partition_evenly(total, burst_count)
    if any(part < min_size or part > max_size for part in parts):
        raise ValueError(
            f"Unable to partition {total} into {burst_count} bursts within range {min_size}-{max_size}"
        )
    return parts


def partition_total_into_bursts(
    total: int,
    *,
    min_size: int,
    max_size: int,
    preferred_size: int,
) -> list[int]:
    if total <= 0:
        return []
    burst_count = choose_burst_count(total, min_size, max_size, preferred_size)
    return partition_total_into_fixed_bursts(
        total,
        burst_count=burst_count,
        min_size=min_size,
        max_size=max_size,
    )


def recent_streak(sequence: Sequence[str], key: str) -> int:
    streak = 0
    for current in reversed(sequence):
        if current != key:
            break
        streak += 1
    return streak


def build_balanced_sequence(
    counts: Mapping[str, int],
    *,
    max_streak: int,
    avoid_first_key: str | None = None,
) -> list[str]:
    remaining = {key: int(value) for key, value in counts.items() if int(value) > 0}
    sequence: list[str] = []

    while remaining:
        candidates = [
            key
            for key, value in remaining.items()
            if value > 0 and recent_streak(sequence, key) < max_streak
        ]
        if not candidates:
            candidates = [key for key, value in remaining.items() if value > 0]
        if not sequence and avoid_first_key is not None:
            non_avoided = [key for key in candidates if key != avoid_first_key]
            if non_avoided:
                candidates = non_avoided

        def score(key: str) -> tuple[int, int, str]:
            return (remaining[key], 0, key)

        chosen = max(candidates, key=score)
        sequence.append(chosen)
        remaining[chosen] -= 1
        if remaining[chosen] <= 0:
            del remaining[chosen]

    return sequence


def same_model_streaks(sequence: Sequence[str]) -> list[tuple[str, int]]:
    if not sequence:
        return []
    streaks: list[tuple[str, int]] = []
    current = sequence[0]
    size = 1
    for item in sequence[1:]:
        if item == current:
            size += 1
            continue
        streaks.append((current, size))
        current = item
        size = 1
    streaks.append((current, size))
    return streaks


def build_evenly_spaced_offsets(
    *,
    minute_index: int,
    count: int,
    slot_ms: int,
    jitter_ms: int,
    rng: random.Random,
    duration_ms: int,
) -> list[int]:
    if count <= 0:
        return []
    minute_start = minute_index * 60_000
    offsets: list[int] = []
    for position in range(count):
        center = minute_start + int(slot_ms * position + (slot_ms / 2))
        jitter = rng.randint(-jitter_ms, jitter_ms)
        bounded = max(minute_start, min(minute_start + 59_999, center + jitter))
        offsets.append(min(bounded, duration_ms - 1))
    return offsets


def count_models_from_payload_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        body = row.get("body_json")
        if not isinstance(body, str):
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        model_name = payload.get("model")
        if not isinstance(model_name, str):
            continue
        counts[model_name] = counts.get(model_name, 0) + 1
    return dict(sorted(counts.items()))
