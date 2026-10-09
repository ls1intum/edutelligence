from .syntax import Expression


class Inferencer:
    """Infer principal types for the exercise's expression subset."""

    def infer_type(self, expression: Expression) -> object:
        del expression
        raise NotImplementedError
