"""The validator: checks a `Netlist` against the numbered rules of docs/ir-spec.md.

Two groups of rules (spec 1.6), each with one checker class behind one public function:

| Rules            | Spec        | Checked by                                   |
| ---------------- | ----------- | -------------------------------------------- |
| F-1 to F-7       | section 9   | `check_fields`, `_FieldChecker`              |
| N-1 to N-4       | section 3   | `check_semantics`, `_SemanticChecker.names`  |
| D-1, D-2         | section 4   | `check_semantics`, `_SemanticChecker.refs`   |
| C-1 to C-5       | section 6   | not yet (step 4)                             |
| A-1 to A-6       | section 7   | not yet (step 5)                             |

`check` runs the field rules, and the semantic rules only when every field rule passes.
"""

import re
from dataclasses import dataclass, fields
from decimal import Decimal
from functools import cache
from types import NoneType, UnionType
from typing import Any, Literal, get_args, get_origin, get_type_hints

from spicule.ir.model import (
    MODEL_CLASSES,
    Call,
    Cell,
    Connection,
    External,
    Instance,
    Netlist,
    NoConnect,
    ParamDecl,
    ParamRef,
    ParamValue,
    Range,
    Signal,
    Slice,
    Subckt,
)

#: Identifiers (spec section 3).
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Expression functions and their number of arguments (spec 7.2).
FUNCTIONS: dict[str, int] = {
    "abs": 1,
    "sqrt": 1,
    "exp": 1,
    "ln": 1,
    "log10": 1,
    "min": 2,
    "max": 2,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Violation:
    """One broken rule."""

    # Spec rule id, e.g. "N-1" or "F-2".
    rule: str
    # Human-readable location, e.g. "cells[2].ports[0].name" or "cell tb, instance dut".
    where: str
    # Descriptive error message.
    message: str
    # The cell and instance the violation is in, when known.
    cell: str | None = None
    instance: str | None = None

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}: {self.message}"


class ValidationError(ValueError):
    """A netlist breaks one or more rules. `violations` lists all of them."""

    def __init__(self, violations: list[Violation]):
        self.violations = violations
        lines = "\n".join(f"  {v}" for v in violations)
        super().__init__(f"invalid netlist, {len(violations)} violation(s):\n{lines}")


def validate(netlist: Netlist) -> None:
    """Raise `ValidationError` unless `netlist` follows every rule of the spec."""
    violations = check(netlist)
    if violations:
        raise ValidationError(violations)


def check(netlist: Netlist) -> list[Violation]:
    """All violations of `netlist`, empty if it is valid. Semantic rules run only once the field rules pass."""
    return check_fields(netlist) or check_semantics(netlist)


def check_fields(obj: Any) -> list[Violation]:
    """Field-rule violations (F-1 to F-7) of a `Netlist`, or of any other model object."""
    return _FieldChecker().run(obj)


def check_semantics(netlist: Netlist) -> list[Violation]:
    """Semantic-rule violations (N, D) of a `Netlist` that passes every field rule."""
    return _SemanticChecker(netlist).run()


class _Checker:
    """Collects violations."""

    def __init__(self) -> None:
        self.violations: list[Violation] = []

    def add(self, rule: str, where: str, message: str, cell: str | None = None, instance: str | None = None) -> None:
        self.violations.append(Violation(rule=rule, where=where, message=message, cell=cell, instance=instance))


# Field rules (spec section 9)


#: Fields that hold an identifier (F-2).
_NAMES = {
    (Subckt, "name"), (External, "name"), (Signal, "name"), (Instance, "name"), (Instance, "cell"),
    (Connection, "port"), (Slice, "signal"), (ParamDecl, "name"), (ParamValue, "name"), (ParamRef, "name"),
}  # fmt: skip


@cache
def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _type_name(tp: Any) -> str:
    if isinstance(tp, UnionType):
        return " | ".join(_type_name(t) for t in get_args(tp))
    if get_origin(tp) is Literal:
        return " | ".join(repr(arg) for arg in get_args(tp))
    if get_origin(tp) is tuple:
        return f"tuple[{_type_name(get_args(tp)[0])}, ...]"
    return "None" if tp is NoneType else tp.__name__


class _FieldChecker(_Checker):
    """F-1 to F-7: one walk over the model, field by field, guided by the dataclass type hints."""

    def run(self, obj: Any) -> list[Violation]:
        if type(obj) not in MODEL_CLASSES:
            self.add("F-1", "netlist", f"expected a model object such as Netlist, got {type(obj).__name__}")
        else:
            self.walk(obj, "", None, None)
        return self.violations

    def walk(self, obj: Any, path: str, cell: str | None, instance: str | None) -> None:
        cls = type(obj)
        # Track the enclosing cell and instance names for the violations below them.
        if cls in (Subckt, External) and isinstance(obj.name, str):
            cell = obj.name
        elif cls is Instance and isinstance(obj.name, str):
            instance = obj.name
        hints = _hints(cls)
        for f in fields(cls):
            value = getattr(obj, f.name)
            where = f"{path}.{f.name}" if path else f.name
            if self.check_type(value, hints[f.name], where, cell, instance):
                self.check_value(obj, f.name, value, where, cell, instance)

    def check_type(self, value: Any, tp: Any, where: str, cell: str | None, instance: str | None) -> bool:
        """F-1, plus F-5 (finite numbers) and F-6 (operators), which need the type. Recurses into the value."""
        for option in get_args(tp) if isinstance(tp, UnionType) else (tp,):
            if get_origin(option) is Literal:
                if value in get_args(option):
                    return True
            elif get_origin(option) is tuple:
                if isinstance(value, tuple):
                    (item_type, _) = get_args(option)
                    for i, item in enumerate(value):
                        self.check_type(item, item_type, f"{where}[{i}]", cell, instance)
                    return True
            elif option is NoneType:
                if value is None:
                    return True
            elif option is int:
                if isinstance(value, int) and not isinstance(value, bool):
                    return True
            elif isinstance(value, option):
                if option is Decimal and not value.is_finite():
                    self.add("F-5", where, f"{value} is not a finite number", cell, instance)
                elif option in MODEL_CLASSES:
                    self.walk(value, where, cell, instance)
                return True
        if get_origin(tp) is Literal:
            self.add("F-6", where, f"operator {value!r} is not one of {' '.join(get_args(tp))}", cell, instance)
        else:
            self.add("F-1", where, f"expected {_type_name(tp)}, got {type(value).__name__} {value!r}", cell, instance)
        return False

    def check_value(self, obj: Any, name: str, value: Any, where: str, cell: str | None, instance: str | None) -> None:
        """F-2, F-3, F-4, F-7 and the function part of F-6, on a value that already has the right type."""
        cls = type(obj)
        if (cls, name) in _NAMES and not NAME_PATTERN.match(value):
            self.add("F-2", where, f"{value!r} is not an identifier ([A-Za-z_][A-Za-z0-9_]*)", cell, instance)
        elif cls is Range and value < 0:
            self.add("F-3", where, f"range index {value} is negative", cell, instance)
        elif cls is NoConnect and value < 1:
            self.add("F-3", where, f"width {value} is less than 1", cell, instance)
        elif cls is Netlist and name == "cells" and not value:
            self.add("F-7", where, "a netlist has at least one cell", cell, instance)
        elif cls is Connection and name == "pieces" and not value:
            self.add("F-4", where, "a connection has at least one piece", cell, instance)
        elif cls is Call and name == "function":
            if value not in FUNCTIONS:
                self.add("F-6", where, f"unknown function {value!r} (known: {', '.join(FUNCTIONS)})", cell, instance)
            elif len(obj.args) != FUNCTIONS[value]:
                arity = FUNCTIONS[value]
                self.add("F-6", where, f"{value}() takes {arity} argument(s), got {len(obj.args)}", cell, instance)


# Semantic rules


class _SemanticChecker(_Checker):
    """N-1 to N-4 (names) and D-1, D-2 (references), on a netlist that passes every field rule."""

    def __init__(self, netlist: Netlist):
        super().__init__()
        self.netlist = netlist
        # Cell name -> position in `Netlist.cells` (the first one, if names clash).
        self.position: dict[str, int] = {}

    def run(self) -> list[Violation]:
        self.names()
        self.refs()
        return self.violations

    def names(self) -> None:
        """N-1 to N-4."""
        for pos, cell in enumerate(self.netlist.cells):
            if cell.name in self.position:
                self.add("N-1", f"cell {cell.name}", "cell name is used more than once", cell.name)
            else:
                self.position[cell.name] = pos
        for cell in self.netlist.cells:
            where = f"cell {cell.name}"
            self.unique("N-2", where, "port or signal", [net.name for net in _nets(cell)], cell.name)
            if isinstance(cell, Subckt):
                self.unique("N-3", where, "instance", [inst.name for inst in cell.instances], cell.name)
            self.unique("N-4", where, "parameter", [param.name for param in cell.params], cell.name)

    def refs(self) -> None:
        """D-1, D-2."""
        for pos, cell in enumerate(self.netlist.cells):
            if not isinstance(cell, Subckt):
                continue
            for inst in cell.instances:
                where = f"cell {cell.name}, instance {inst.name}"
                target = self.position.get(inst.cell)
                if target is None:
                    message = f"instantiates {inst.cell!r}, which is not a cell of the netlist"
                    self.add("D-1", where, message, cell.name, inst.name)
                elif target >= pos:
                    message = f"instantiates {inst.cell!r}, which comes later in the netlist (define before use)"
                    self.add("D-2", where, message, cell.name, inst.name)

    def unique(self, rule: str, where: str, what: str, names: list[str], cell: str) -> None:
        seen: set[str] = set()
        for name in names:
            if name in seen:
                self.add(rule, where, f"{what} name {name!r} is used more than once", cell)
            seen.add(name)


def _nets(cell: Cell) -> tuple[Signal, ...]:
    """Every net of a cell: its ports, plus the internal signals of a `Subckt`."""
    return cell.ports + cell.signals if isinstance(cell, Subckt) else cell.ports
