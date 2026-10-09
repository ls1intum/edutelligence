from .model import CellRef


class EvaluationTrace:
    def __init__(self) -> None:
        self._visited: list[CellRef] = []

    def record(self, ref: CellRef) -> None:
        self._visited.append(ref)

    def visited(self) -> tuple[CellRef, ...]:
        return tuple(self._visited)
