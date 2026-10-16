from .dependency_graph import DependencyGraph
from .diagnostics import EvaluationTrace
from .errors import FormulaCycleError
from .model import CellRef, Formula
from .store import CellStore
from .value_cache import ValueCache, is_missing


class WorkbookEngine:
    """Evaluate workbook formulas and maintain incremental cached results."""

    def __init__(self) -> None:
        self._store = CellStore()
        self._graph = DependencyGraph()
        self._cache = ValueCache()
        self.trace = EvaluationTrace()

    def set_value(self, ref: CellRef, value: int) -> None:
        self._store.set_value(ref, value)
        self._graph.replace_dependencies(ref, ())
        self._cache.discard_all(self._graph.affected_by(ref))

    def set_formula(self, ref: CellRef, formula: Formula) -> None:
        self._store.set_formula(ref, formula)
        self._graph.replace_dependencies(ref, formula.dependencies)
        self._cache.discard_all(self._graph.affected_by(ref))

    def value(self, ref: CellRef) -> int:
        return self._evaluate(ref, set())

    def _evaluate(self, ref: CellRef, active: set[CellRef]) -> int:
        cached = self._cache.get(ref)
        if not is_missing(cached):
            return int(cached)
        if ref in active:
            raise FormulaCycleError(f"cycle at {ref.sheet}!{ref.cell}")
        active.add(ref)
        self.trace.record(ref)
        try:
            stored = self._store.value(ref)
            if stored is not None:
                result = stored
            else:
                formula = self._store.formula(ref)
                if formula is None:
                    raise KeyError(f"unknown cell {ref.sheet}!{ref.cell}")
                result = formula.offset + sum(
                    self._evaluate(dependency, active)
                    for dependency in formula.dependencies
                )
            self._cache.put(ref, result)
            return result
        finally:
            active.remove(ref)
