import zlib

MAX_PARALLELISM = 128


def key_group(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) % MAX_PARALLELISM


def owner_for_group(group: int, parallelism: int) -> int:
    if parallelism < 1:
        raise ValueError("parallelism must be positive")
    return min(parallelism - 1, group * parallelism // MAX_PARALLELISM)
