"""The circuit model: the circuit part of a SPICE deck as frozen dataclasses.

The rules a valid `Netlist` follows are numbered in docs/ir-spec.md.
Why the model looks like this is in docs/ir-decisions.md.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal, TypeGuard

_model = dataclass(frozen=True, slots=True, kw_only=True)

IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"

_IDENTIFIER = re.compile(IDENTIFIER)


def is_identifier(text: object) -> TypeGuard[str]:
    return isinstance(text, str) and _IDENTIFIER.fullmatch(text) is not None


# --- Expressions ---


@_model
class Number:
    value: Decimal


@_model
class ParamRef:
    name: str


@_model
class Neg:
    operand: Expr


@_model
class Binary:
    op: Literal["+", "-", "*", "/"]
    left: Expr
    right: Expr


@_model
class Call:
    function: str
    args: tuple[Expr, ...]


Expr = Number | ParamRef | Neg | Binary | Call


@_model
class Expression:
    root: Expr


# --- Parameters ---


class ParamType(Enum):
    NUMBER = "number"  # Values are `Expression`s (like `w` or `h`).
    STRING = "string"  # Values are `str`s (like `file`).


Value = Expression | str


@_model
class ParamDecl:
    name: str
    type: ParamType
    default: Value


@_model
class ParamValue:
    name: str
    value: Value


# --- Connections ---


@_model
class Range:
    msb: int
    lsb: int


@_model
class Signal:
    name: str
    range: Range | None = None  # None: scalar signal


@_model
class SignalRef:
    signal: str
    range: Range | None = None  # None: entire signal (all bits, 1 if refers to scalar)


@_model
class NoConnect:
    width: int


Piece = SignalRef | NoConnect


@_model
class Connection:
    port: str
    pieces: tuple[Piece, ...]


# --- Cells ---


@_model
class Meta:
    origin: str | None = None  # Source location of the node (eg "tb/tb_inv.py:30")


@_model
class Instance:
    name: str
    cell: str
    connections: tuple[Connection, ...] = ()
    params: tuple[ParamValue, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


@_model
class Subckt:
    name: str
    ports: tuple[Signal, ...] = ()
    params: tuple[ParamDecl, ...] = ()
    signals: tuple[Signal, ...] = ()
    instances: tuple[Instance, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


class Element(Enum):
    SUBCKT = "subckt"
    MOS = "mos"
    DIODE = "diode"
    BIPOLAR = "bipolar"
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    BUILTIN = "builtin"


@_model
class External:
    name: str
    element: Element
    ports: tuple[Signal, ...] = ()
    meta: Meta = field(default=Meta(), compare=False)


Cell = Subckt | External


# --- Netlist ---


# A weakref slot lets the validator remember which netlist objects already passed (spicule.ir.validator).
@dataclass(frozen=True, slots=True, kw_only=True, weakref_slot=True)
class Netlist:
    cells: tuple[Cell, ...] = ()


MODEL_CLASSES = (
    Number, ParamRef, Neg, Binary, Call, Expression, ParamDecl, ParamValue,
    Range, Signal, SignalRef, NoConnect, Connection, Meta, Instance, Subckt, External, Netlist,
)  # fmt: skip
