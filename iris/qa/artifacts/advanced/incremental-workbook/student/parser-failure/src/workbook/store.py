from .model import CellRef, Formula


class CellStore:
    """Keep literal values and formulas separate from evaluation concerns."""

    def __init__(self) -> None:
        self._values: dict[CellRef, int] = {}
        self._formulas: dict[CellRef, Formula] = {}

    def set_value(self, ref: CellRef, value: int) -> None:
        self._values[ref] = value
        self._formulas.pop(ref, None)

    def set_formula(self, ref: CellRef, formula: Formula) -> None:
        self._formulas[ref] = formula
        self._values.pop(ref, None)

    def value(self, ref: CellRef) -> int | None:
        return self._values.get(ref)

    def formula(self, ref: CellRef) -> Formula | None:
        return self._formulas.get(ref)
