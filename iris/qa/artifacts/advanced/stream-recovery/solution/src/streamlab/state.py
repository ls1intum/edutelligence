from collections.abc import Mapping

from .hashing import key_group, owner_for_group

Snapshot = dict[int, dict[str, int]]


def partition_snapshot(values: Mapping[str, int], parallelism: int) -> Snapshot:
    del parallelism
    snapshot: Snapshot = {}
    for key, value in values.items():
        snapshot.setdefault(key_group(key), {})[key] = value
    return snapshot


def restore_worker(
    snapshot: Mapping[int, Mapping[str, int]], worker: int, parallelism: int
) -> dict[str, int]:
    restored: dict[str, int] = {}
    for group, values in snapshot.items():
        if owner_for_group(group, parallelism) == worker:
            restored.update(values)
    return restored
