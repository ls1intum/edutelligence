def owner_for_key(key: str, parallelism: int) -> int:
    if parallelism < 1:
        raise ValueError("parallelism must be positive")
    return hash(key) % parallelism
