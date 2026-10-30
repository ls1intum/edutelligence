def partition_snapshot(values: dict[str, int], parallelism: int) -> dict:
    raise NotImplementedError


def restore_worker(snapshot: dict, worker: int, parallelism: int) -> dict[str, int]:
    raise NotImplementedError
