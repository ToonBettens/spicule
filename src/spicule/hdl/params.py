"""Netlist parameters and expressions.

A netlist parameter is written into the netlist and evaluated by the simulator. Python operators on it don't
calculate: they build an expression tree, written out for the simulator::

    nfin = h.Param(default=2)
    w = h.Param(default=1e-6)
    r0 = res(r=2 * nfin + w)(p=a, n=b)

The value passed to parameter `r` is a `ParamExpr`: a handle on a tree::

    ParamExpr
      +-- _Op: +
            +-- _Op: *
            |     +-- Decimal: 2
            |     +-- Param: nfin
            +-- Param: w
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from spicule import ir
from spicule.hdl.source import HdlError, Source, caller, check_identifier

# --- Expressions ---


@dataclass(frozen=True, slots=True, eq=False)
class _Op:
    """An operator or function node: `op` is `+ - * /`, `neg`, or a function name."""

    op: str
    args: tuple[_Node, ...]


# A node of an HDL expression tree. Parameters stay objects until elaboration, because a parameter in a class body
# only gets its name once the class is complete.
type _Node = Decimal | Param | _Op


class ParamExpr:
    """A numeric expression over netlist parameters: a handle on a tree. Python operators build a new one."""

    __slots__ = ("node",)

    def __init__(self, node: _Node):
        self.node = node

    @property
    def refs(self) -> list[Param]:
        """The parameters the expression uses, each once, in order of appearance."""
        return list(dict.fromkeys(_params(self.node)))  # A `Param` hashes by identity

    def to_ir(self) -> ir.Expression:
        return ir.Expression(root=_to_ir(self.node))

    def __repr__(self) -> str:
        return f"ParamExpr({_text(self.node)})"

    def __bool__(self) -> bool:
        raise HdlError("netlist parameter expressions have no truth value: the simulator evaluates them", caller())

    def _bin(self, op: str, other: Any, reflected: bool = False) -> ParamExpr:
        mine, theirs = self.node, as_expr(other, caller()).node
        left, right = (theirs, mine) if reflected else (mine, theirs)
        return ParamExpr(_Op(op, (left, right)))

    def __add__(self, o: Any) -> ParamExpr:
        return self._bin("+", o)

    def __radd__(self, o: Any) -> ParamExpr:
        return self._bin("+", o, True)

    def __sub__(self, o: Any) -> ParamExpr:
        return self._bin("-", o)

    def __rsub__(self, o: Any) -> ParamExpr:
        return self._bin("-", o, True)

    def __mul__(self, o: Any) -> ParamExpr:
        return self._bin("*", o)

    def __rmul__(self, o: Any) -> ParamExpr:
        return self._bin("*", o, True)

    def __truediv__(self, o: Any) -> ParamExpr:
        return self._bin("/", o)

    def __rtruediv__(self, o: Any) -> ParamExpr:
        return self._bin("/", o, True)

    def __pow__(self, o: Any) -> ParamExpr:
        return self._bin("pow", o)

    def __rpow__(self, o: Any) -> ParamExpr:
        return self._bin("pow", o, True)

    def __neg__(self) -> ParamExpr:
        return ParamExpr(_Op("neg", (self.node,)))

    def __pos__(self) -> ParamExpr:
        return self


# --- Declarations ---


class Param(ParamExpr):
    """
    A netlist parameter of a subckt: a number with a default, `h.Param(default=1e3)`. No instance has to set it. The
    default may use parameters declared before it. A parameter is also the smallest expression: itself, as a leaf.
    """

    def __init__(self, *, default: Any):
        super().__init__(self)
        self.source = caller()
        self.name: str | None = None
        self.owner: object | None = None  # The subckt (class) it belongs to
        self.default = as_number(default, "default of parameter", self.source)

    def __set_name__(self, owner: object, name: str) -> None:
        if self.owner is not None and self.owner is not owner:
            raise HdlError(f"parameter {self.name!r} already belongs to {self.owner}", self.source)
        if self.owner is not None and self.name != name:
            raise HdlError(f"parameter {self.name!r} can't also be named {name!r}; create a new one", self.source)
        self.name = check_identifier(name, "parameter name", self.source)
        self.owner = owner

    def to_decl(self) -> ir.ParamDecl:
        assert self.name is not None
        return ir.ParamDecl(name=self.name, default=self.default.to_ir())

    def __repr__(self) -> str:
        return f"Param({self.name or '?'})"


# --- Functions ---


def _call(function: str, *args: Any) -> ParamExpr:
    source = caller()
    return ParamExpr(_Op(function, tuple(as_expr(a, source).node for a in args)))


class fn:
    """Functions for netlist parameter expressions (spec section 7.2)."""

    @staticmethod
    def abs(x: Any) -> ParamExpr:
        return _call("abs", x)

    @staticmethod
    def sqrt(x: Any) -> ParamExpr:
        return _call("sqrt", x)

    @staticmethod
    def exp(x: Any) -> ParamExpr:
        return _call("exp", x)

    @staticmethod
    def ln(x: Any) -> ParamExpr:
        return _call("ln", x)

    @staticmethod
    def log10(x: Any) -> ParamExpr:
        return _call("log10", x)

    @staticmethod
    def min(x: Any, y: Any) -> ParamExpr:
        return _call("min", x, y)

    @staticmethod
    def max(x: Any, y: Any) -> ParamExpr:
        return _call("max", x, y)

    @staticmethod
    def pow(x: Any, y: Any) -> ParamExpr:
        return _call("pow", x, y)


# --- Values ---

#: A parameter value as the HDL holds it: an expression, or a text (only on instances of external cells).
type HdlValue = ParamExpr | str


def as_number(value: Any, what: str, source: Source | None) -> ParamExpr:
    """A value for a subckt parameter: a number or an expression."""
    if isinstance(value, str):
        raise HdlError(
            f"{what} is a number, got the text {value!r}. Subckt parameters are numbers; a text choice is a build "
            f"parameter of a generator",
            source,
        )
    return as_expr(value, source, what)


def to_value(value: Any, what: str, source: Source | None) -> HdlValue:
    """A value for a parameter of an external cell: a `str` stays text, anything else becomes a number expression."""
    return value if isinstance(value, str) else as_expr(value, source, what)


def as_expr(value: Any, source: Source | None, what: str = "expression operand") -> ParamExpr:
    """A `Param`, `ParamExpr` or Python number as an expression."""
    return value if isinstance(value, ParamExpr) else ParamExpr(to_decimal(value, what, source))


def to_decimal(value: object, what: str, source: Source | None) -> Decimal:
    """A Python number as an exact `Decimal`. Floats go through their shortest text: `1.6e-08` is exactly 16e-9."""
    if isinstance(value, bool):
        raise HdlError(f"{what}: {value!r} is not a number (use 0 or 1)", source)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HdlError(f"{what}: {value!r} is not a finite number", source)
        return Decimal(repr(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise HdlError(f"{what}: {value!r} is not a finite number", source)
        return value
    raise HdlError(f"{what}: {value!r} is not a number", source)


def refs(value: HdlValue) -> list[Param]:
    """The parameters a value uses."""
    return [] if isinstance(value, str) else value.refs


# --- To the IR ---


def value_ir(value: HdlValue) -> ir.Value:
    return value if isinstance(value, str) else value.to_ir()


def _params(node: _Node) -> Iterator[Param]:
    if isinstance(node, Param):
        yield node
    elif isinstance(node, _Op):
        for arg in node.args:
            yield from _params(arg)


def _to_ir(node: _Node) -> ir.Expr:
    match node:
        case Decimal():
            return ir.Number(value=node) if node >= 0 else ir.Neg(operand=ir.Number(value=-node))
        case Param():
            assert node.name is not None  # checked by elaborate()
            return ir.ParamRef(name=node.name)
        case _Op(op="neg", args=(operand,)):
            return ir.Neg(operand=_to_ir(operand))
        case _Op(op="+" | "-" | "*" | "/" as op, args=(left, right)):
            return ir.Binary(op=op, left=_to_ir(left), right=_to_ir(right))
        case _Op(op=function, args=args):
            return ir.Call(function=function, args=tuple(_to_ir(a) for a in args))


def _text(node: _Node) -> str:
    """Text for `repr`, fully parenthesized."""
    match node:
        case Decimal():
            return str(node)
        case Param():
            return node.name or "?"
        case _Op(op="+" | "-" | "*" | "/" as op, args=(left, right)):
            return f"({_text(left)}{op}{_text(right)})"
        case _Op(op="neg", args=(operand,)):
            return f"-{_text(operand)}"
        case _Op(op=function, args=args):
            return f"{function}({', '.join(_text(a) for a in args)})"
