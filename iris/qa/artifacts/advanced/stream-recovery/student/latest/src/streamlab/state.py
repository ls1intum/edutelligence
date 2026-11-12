from collections.abc import Mapping

from .hashing import owner_for_key

Snapshot = dict[int, dict[str, int]]


def partition_snapshot(values: Mapping[str, int], parallelism: int) -> Snapshot:
    snapshot: Snapshot = {}
    for key, value in values.items():
        snapshot.setdefault(owner_for_key(key, parallelism), {})[key] = value
    return snapshot


def restore_worker(
    snapshot: Mapping[int, Mapping[str, int]], worker: int, parallelism: int
) -> dict[str, int]:
    del parallelism
    return dict(snapshot.get(worker, {}))
