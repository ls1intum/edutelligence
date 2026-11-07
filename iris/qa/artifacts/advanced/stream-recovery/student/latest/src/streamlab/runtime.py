from .checkpoint import BarrierAligner, Checkpoint
from .model import Record


class Runtime:
    """Process records and coordinate checkpoints."""

    def __init__(self, input_count: int = 2):
        self.state: dict[str, int] = {}
        self.aligner = BarrierAligner(input_count)

    def process(self, record: Record) -> None:
        for ready in self.aligner.handle_record(record):
            self.state[ready.key] = self.state.get(ready.key, 0) + ready.delta

    def barrier(self, input_id: int, checkpoint_id: int) -> Checkpoint | None:
        checkpoint, replay = self.aligner.handle_barrier(
            input_id, checkpoint_id, lambda: self.state
        )
        for record in replay:
            self.process(record)
        return checkpoint
