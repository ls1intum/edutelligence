from .model import CellRef, Formula


def parse_formula(current_sheet: str, text: str) -> Formula:
    expression = text.removeprefix("=")
    terms = [part.strip() for part in expression.split("+")]
    dependencies: list[CellRef] = []
    offset = 0
    for term in terms:
        if term.lstrip("-").isdigit():
            offset += int(term)
        elif "!" in term:
            sheet, cell = term.split("!", 1)
            dependencies.append(CellRef(sheet, cell))
        else:
            dependencies.append(CellRef(current_sheet, term))
    return Formula(tuple(dependencies), offset)
