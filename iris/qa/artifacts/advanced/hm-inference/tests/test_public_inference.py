from infer import (
    Apply,
    BoolLiteral,
    Inferencer,
    IntLiteral,
    Lambda,
    Let,
    Pair,
    TBool,
    TInt,
    TPair,
    Var,
)


def test_identity_accepts_an_integer() -> None:
    expression = Apply(Lambda("x", Var("x")), IntLiteral(1))

    assert Inferencer().infer_type(expression) == TInt()


def test_let_identity_can_be_used_at_two_concrete_types() -> None:
    expression = Let(
        "id",
        Lambda("x", Var("x")),
        Pair(
            Apply(Var("id"), IntLiteral(1)),
            Apply(Var("id"), BoolLiteral(True)),
        ),
    )

    assert Inferencer().infer_type(expression) == TPair(TInt(), TBool())
