from .model import CellRef, Formula


def parse_formula(current_sheet: str, text: str) -> Formula:
    expression = text.removeprefix("=")
    terms = [part.strip() for part in expression.split("+")]
    dependencies: list[CellRef] = []
    offset = 0
    for term in terms:
        if term.lstrip("-").isdigit():
            offset += int(term)
        else:
            dependencies.append(CellRef(current_sheet, term))
    return Formula(tuple(dependencies), offset)
