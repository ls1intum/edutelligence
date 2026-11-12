from collections.abc import Callable
from dataclasses import dataclass

from .model import Record


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: int
    state: dict[str, int]


class BarrierAligner:
    """Align checkpoint barriers across all runtime inputs."""

    def __init__(self, input_count: int):
        self._input_count = input_count
        self._blocked: set[int] = set()
        self._buffers: dict[int, list[Record]] = {
            input_id: [] for input_id in range(input_count)
        }
        self._pending: Checkpoint | None = None

    def handle_record(self, record: Record) -> list[Record]:
        if record.input_id in self._blocked:
            self._buffers[record.input_id].append(record)
            return []
        return [record]

    def handle_barrier(
        self,
        input_id: int,
        checkpoint_id: int,
        snapshotter: Callable[[], dict[str, int]],
    ) -> tuple[Checkpoint | None, list[Record]]:
        self._blocked.add(input_id)
        if self._pending is None:
            self._pending = Checkpoint(checkpoint_id, dict(snapshotter()))
        if len(self._blocked) != self._input_count:
            return None, []

        checkpoint = self._pending
        replay = [
            record
            for buffered_input in sorted(self._buffers)
            for record in self._buffers[buffered_input]
        ]
        self._pending = None
        self._blocked.clear()
        for records in self._buffers.values():
            records.clear()
        return checkpoint, replay
