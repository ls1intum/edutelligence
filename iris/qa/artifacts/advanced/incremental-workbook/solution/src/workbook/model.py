from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CellRef:
    sheet: str
    cell: str


@dataclass(frozen=True, slots=True)
class Formula:
    dependencies: tuple[CellRef, ...]
    offset: int = 0
