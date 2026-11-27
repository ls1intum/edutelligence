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
        affected = {ref, *self._graph.direct_dependents(ref)}
        self._cache.discard_all(affected)

    def set_formula(self, ref: CellRef, formula: Formula) -> None:
        self._store.set_formula(ref, formula)
        self._graph.replace_dependencies(ref, formula.dependencies)
        affected = {ref, *self._graph.direct_dependents(ref)}
        self._cache.discard_all(affected)

    def value(self, ref: CellRef) -> int:
        return self._evaluate(ref, set())

    def _evaluate(self, ref: CellRef, seen: set[CellRef]) -> int:
        if ref in seen:
            raise FormulaCycleError(f"cycle at {ref.sheet}!{ref.cell}")
        cached = self._cache.get(ref)
        if not is_missing(cached):
            return int(cached)
        seen.add(ref)
        self.trace.record(ref)
        stored = self._store.value(ref)
        if stored is not None:
            result = stored
        else:
            formula = self._store.formula(ref)
            if formula is None:
                raise KeyError(f"unknown cell {ref.sheet}!{ref.cell}")
            result = formula.offset + sum(
                self._evaluate(dependency, seen) for dependency in formula.dependencies
            )
        self._cache.put(ref, result)
        return result
