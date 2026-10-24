from .model import CellRef, Formula


class WorkbookEngine:
    def set_value(self, ref: CellRef, value: int) -> None:
        raise NotImplementedError

    def set_formula(self, ref: CellRef, formula: Formula) -> None:
        raise NotImplementedError

    def value(self, ref: CellRef) -> int:
        raise NotImplementedError
