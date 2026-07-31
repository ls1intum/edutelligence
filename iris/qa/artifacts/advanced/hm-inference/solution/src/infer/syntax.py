from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class Var:
    name: str


@dataclass(frozen=True, slots=True)
class Lambda:
    parameter: str
    body: "Expression"


@dataclass(frozen=True, slots=True)
class Apply:
    function: "Expression"
    argument: "Expression"


@dataclass(frozen=True, slots=True)
class Let:
    name: str
    value: "Expression"
    body: "Expression"


@dataclass(frozen=True, slots=True)
class Pair:
    left: "Expression"
    right: "Expression"


@dataclass(frozen=True, slots=True)
class IntLiteral:
    value: int


@dataclass(frozen=True, slots=True)
class BoolLiteral:
    value: bool


Expression: TypeAlias = Var | Lambda | Apply | Let | Pair | IntLiteral | BoolLiteral
