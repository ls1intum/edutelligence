from .model import CellRef

_MISSING = object()


class ValueCache:
    """Cache evaluated values by their complete workbook cell identity."""

    def __init__(self) -> None:
        self._values: dict[CellRef, int] = {}

    def get(self, ref: CellRef) -> int | object:
        return self._values.get(ref, _MISSING)

    def put(self, ref: CellRef, value: int) -> None:
        self._values[ref] = value

    def discard_all(self, refs: set[CellRef]) -> None:
        for ref in refs:
            self._values.pop(ref, None)


def is_missing(value: int | object) -> bool:
    return value is _MISSING
