from collections import defaultdict, deque

from .model import CellRef


class DependencyGraph:
    """Track reverse formula dependencies for targeted invalidation."""

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

    def affected_by(self, source: CellRef) -> set[CellRef]:
        affected = {source}
        queue = deque([source])
        while queue:
            current = queue.popleft()
            for dependent in self._dependents.get(current, set()):
                if dependent not in affected:
                    affected.add(dependent)
                    queue.append(dependent)
        return affected
