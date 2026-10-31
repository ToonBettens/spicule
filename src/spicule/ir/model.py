"""The circuit model: the circuit part of a SPICE deck as frozen dataclasses.

The rules a valid `Netlist` follows are numbered in docs/ir-spec.md.
Why the model looks like this is in docs/ir-decisions.md.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal

_model = dataclass(frozen=True, slots=True, kw_only=True)


class Element(Enum):
    """Where the name of an external cell lives, and so how a netlist line calls it."""

    SUBCKT = "subckt"  # X
    MOS = "mos"  # M
    DIODE = "diode"  # D
    BIPOLAR = "bipolar"  # Q
    RESISTOR = "resistor"  # R
    CAPACITOR = "capacitor"  # C
    INDUCTOR = "inductor"  # L
    BUILTIN = "builtin"  # Simulator built-in, referred to by its name.


class ParamType(Enum):
    NUMBER = "number"  # Values are `Expression`s (like `w` or `h`).
    STRING = "string"  # Values are `str`s (like `file`).


@_model
class Meta:
    """Annotations on a node of the hierarchy that never affect meaning."""

    origin: str | None = None  # Source location of the node (eg "tb/tb_inv.py:30")


@_model
class Range:
    """
    A bus range. `msb` is the left index and `lsb` the right one, and either
    may be the larger. Expansion runs left to right.
    """

    msb: int
    lsb: int


@_model
class Signal:
    """A net of a cell: a port or an internal signal."""

    name: str
    range: Range | None = None


# Expression trees. Nodes compare structurally: `w*2` and `w * 2` give the same tree, `2*w`
# and `w*2` don't (no algebra). Parentheses leave no trace, because precedence is in the shape.


@_model
class Number:
    """A number in an expression."""

    value: Decimal


@_model
class ParamRef:
    """A reference to a number parameter of the enclosing cell."""

    name: str


@_model
class Neg:
    """Negation. The parser drops a unary `+`, so this is the only unary node."""

    operand: Expr


@_model
class Binary:
    # "^" is exponentiation.
    op: Literal["+", "-", "*", "/", "^"]
    left: Expr
    right: Expr


@_model
class Call:
    """A call of one of the functions of spec section 7.2."""

    function: str
    args: tuple[Expr, ...]


#: An expression tree node.
Expr = Number | ParamRef | Neg | Binary | Call


@_model
class Expression:
    """
    A numeric value, evaluated by the simulator. A plain number is the smallest expression
    (`Expression(root=Number(...))`), so every numeric value has exactly one representation. Held
    as a tree, so equal expressions compare equal however they were spelled.
    """

    root: Expr


#: A parameter value: an expression (ParamType.NUMBER) or a text (ParamType.STRING).
Value = Expression | str


@_model
class ParamDecl:
    """A declared netlist parameter of a cell."""

    name: str
    type: ParamType
    default: Value | None = None  # None: required parameter


@_model
class ParamValue:
    """A parameter value set on an instance."""

    name: str
    value: Value


@_model
class Slice:
    """
    Bits of a port or internal signal of the containing cell. No range: the whole signal. With a
    range (bus signals only): those bits, in either direction.
    """

    signal: str
    range: Range | None = None


@_model
class NoConnect:
    """Bits deliberately left open. Writers give each bit a unique net."""

    width: int


#: One piece of a connection.
Piece = Slice | NoConnect


@_model
class Connection:
    """
    What one port of an instance connects to: pieces in expansion order, first piece to the
    port's first bit. Pieces are in canonical form (longest runs), so every connection has
    exactly one representation.
    """

    port: str
    pieces: tuple[Piece, ...]


@_model
class Instance:
    name: str
    cell: str
    connections: tuple[Connection, ...] = ()
    params: tuple[ParamValue, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


@_model
class Subckt:
    """A cell defined here: a `.subckt`."""

    name: str
    ports: tuple[Signal, ...] = ()
    params: tuple[ParamDecl, ...] = ()
    signals: tuple[Signal, ...] = ()
    instances: tuple[Instance, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


@_model
class External:
    """A cell defined elsewhere: `element` says where its name lives."""

    name: str
    element: Element
    ports: tuple[Signal, ...] = ()
    params: tuple[ParamDecl, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


#: A cell of a netlist.
Cell = Subckt | External


@_model
class Netlist:
    """
    One or more top cells and every cell they use, each once, leaves first. Cell names are
    unique and final: writers print them as they are.
    """

    cells: tuple[Cell, ...] = ()


MODEL_CLASSES = (
    Netlist, Subckt, External, Signal, Range, Instance, Connection, Slice, NoConnect,
    ParamDecl, ParamValue, Meta, Expression, Number, ParamRef, Neg, Binary, Call,
)  # fmt: skip
