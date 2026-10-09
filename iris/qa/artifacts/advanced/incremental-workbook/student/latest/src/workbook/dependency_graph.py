from collections import defaultdict

from .model import CellRef


class DependencyGraph:
    """Track the direct reverse dependencies currently known to the workbook."""

    def __init__(self) -> None:
        self._dependencies: dict[CellRef, set[CellRef]] = {}
        self._dependents: dict[CellRef, set[CellRef]] = defaultdict(set)

    def replace_dependencies(
        self, target: CellRef, dependencies: tuple[CellRef, ...]
    ) -> None:
        for previous in self._dependencies.get(target, set()):
            self._dependents[previous].discard(target)
        current = set(dependencies)
        self._dependencies[target] = current
        for dependency in current:
            self._dependents[dependency].add(target)

    def direct_dependents(self, source: CellRef) -> set[CellRef]:
        return set(self._dependents.get(source, set()))
