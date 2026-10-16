from workbook import CellRef, Formula, FormulaCycleError, WorkbookEngine


def test_evaluates_a_simple_dependency_chain() -> None:
    engine = WorkbookEngine()
    source = CellRef("Inputs", "A1")
    total = CellRef("Summary", "B1")
    engine.set_value(source, 4)
    engine.set_formula(total, Formula((source,), offset=3))

    assert engine.value(total) == 7


def test_rejects_a_direct_cycle() -> None:
    engine = WorkbookEngine()
    left = CellRef("Summary", "A1")
    right = CellRef("Summary", "B1")
    engine.set_formula(left, Formula((right,)))
    engine.set_formula(right, Formula((left,)))

    try:
        engine.value(left)
    except FormulaCycleError:
        return
    raise AssertionError("direct cycle was accepted")
