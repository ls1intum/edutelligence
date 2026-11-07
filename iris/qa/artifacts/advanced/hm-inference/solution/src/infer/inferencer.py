from .environment import TypeEnvironment
from .scheme import Scheme
from .substitution import Substitution
from .syntax import Apply, BoolLiteral, Expression, IntLiteral, Lambda, Let, Pair, Var
from .types import (
    Monotype,
    TBool,
    TFunction,
    TInt,
    TPair,
    TVariable,
    free_type_variables,
)
from .unification import unify


class Inferencer:
    """Infer principal types for the exercise's Hindley-Milner expression subset."""

    def __init__(self) -> None:
        self._next_identifier = 0

    def fresh(self) -> TVariable:
        result = TVariable(self._next_identifier)
        self._next_identifier += 1
        return result

    def infer_type(self, expression: Expression) -> Monotype:
        substitution, inferred = self._infer(expression, TypeEnvironment())
        return substitution.apply_type(inferred)

    def _infer(
        self, expression: Expression, environment: TypeEnvironment
    ) -> tuple[Substitution, Monotype]:
        if isinstance(expression, IntLiteral):
            return Substitution(), TInt()
        if isinstance(expression, BoolLiteral):
            return Substitution(), TBool()
        if isinstance(expression, Var):
            return Substitution(), environment.lookup(expression.name).instantiate(
                self.fresh
            )
        if isinstance(expression, Lambda):
            parameter_type = self.fresh()
            local = environment.extend(
                expression.parameter, Scheme(frozenset(), parameter_type)
            )
            substitution, body_type = self._infer(expression.body, local)
            return substitution, TFunction(
                substitution.apply_type(parameter_type), body_type
            )
        if isinstance(expression, Apply):
            function_substitution, function_type = self._infer(
                expression.function, environment
            )
            argument_substitution, argument_type = self._infer(
                expression.argument, environment.apply(function_substitution)
            )
            result_type = self.fresh()
            call_substitution = unify(
                argument_substitution.apply_type(function_type),
                TFunction(argument_type, result_type),
            )
            combined = call_substitution.compose(
                argument_substitution.compose(function_substitution)
            )
            return combined, call_substitution.apply_type(result_type)
        if isinstance(expression, Let):
            value_substitution, value_type = self._infer(expression.value, environment)
            current_environment = environment.apply(value_substitution)
            current_type = value_substitution.apply_type(value_type)
            quantified = (
                free_type_variables(current_type)
                - current_environment.free_type_variables()
            )
            scheme = Scheme(frozenset(quantified), current_type)
            body_substitution, body_type = self._infer(
                expression.body, current_environment.extend(expression.name, scheme)
            )
            return body_substitution.compose(value_substitution), body_type
        if isinstance(expression, Pair):
            left_substitution, left_type = self._infer(expression.left, environment)
            right_substitution, right_type = self._infer(
                expression.right, environment.apply(left_substitution)
            )
            return right_substitution.compose(left_substitution), TPair(
                right_substitution.apply_type(left_type), right_type
            )
        raise TypeError(f"unsupported expression {expression!r}")
