import json


def encode_snapshot(values: dict[str, int]) -> str:
    return json.dumps({key: value for key, value in values.items() if value >= 0})


def decode_snapshot(payload: str) -> dict[str, int]:
    return {key: int(value) for key, value in json.loads(payload).items()}
