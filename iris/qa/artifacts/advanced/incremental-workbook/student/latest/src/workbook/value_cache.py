from .model import CellRef

_MISSING = object()


class ValueCache:
    """Cache previously evaluated workbook values."""

    def __init__(self) -> None:
        self._values: dict[str, int] = {}

    def get(self, ref: CellRef) -> int | object:
        return self._values.get(ref.cell, _MISSING)

    def put(self, ref: CellRef, value: int) -> None:
        self._values[ref.cell] = value

    def discard_all(self, refs: set[CellRef]) -> None:
        for ref in refs:
            self._values.pop(ref.cell, None)


def is_missing(value: int | object) -> bool:
    return value is _MISSING
