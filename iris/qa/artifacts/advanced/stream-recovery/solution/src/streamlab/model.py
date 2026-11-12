from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Record:
    input_id: int
    key: str
    timestamp_ms: int
    delta: int
