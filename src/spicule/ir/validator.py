"""The validator: checks a `Netlist`.

Two groups of rules (docs/ir-spec.md)., each with one checker class behind one public function:

| Rules            | Spec        | Checked by                                   |
| ---------------- | ----------- | -------------------------------------------- |
| F-1 to F-7       | section 9   | `check_fields`, `_FieldChecker`              |
| N-1 to N-4       | section 3   | `check_semantics`, `_SemanticChecker.names`  |
| D-1, D-2         | section 4   | `check_semantics`, `_SemanticChecker.refs`   |
| C-1 to C-5       | section 6   | `check_semantics`, `_SemanticChecker.conns`  |
| A-1 to A-5       | section 7   | `check_semantics`, `_SemanticChecker.params` |
| W-1 to W-3       | section 6.4 | `lint` (warnings, on a valid netlist)        |

`check` runs the field rules, and the semantic rules only when every field rule passes.
"""

import weakref
from dataclasses import dataclass, fields
from decimal import Decimal
from functools import cache
from types import NoneType, UnionType
from typing import Any, Literal, get_args, get_origin, get_type_hints

from spicule.ir.connections import OPEN, NetBit, bits, canonical_pieces, nets, signal_bits, width
from spicule.ir.expressions import FUNCTIONS, param_refs
from spicule.ir.model import (
    IDENTIFIER,
    MODEL_CLASSES,
    Call,
    Cell,
    Connection,
    Expression,
    External,
    Instance,
    Netlist,
    NoConnect,
    Number,
    ParamDecl,
    ParamRef,
    ParamValue,
    Piece,
    Range,
    Signal,
    SignalRef,
    Subckt,
    Value,
    is_identifier,
)


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


# Identities of the netlist objects that passed `validate`. A netlist is
# immutable, so it stays valid. An entry is #: dropped when its netlist is
# garbage-collected, before its id can be reused.
_validated: set[int] = set()


def validate(netlist: Netlist) -> None:
    """
    Raise `ValidationError` unless `netlist` follows every rule of the spec. A netlist object that passed before
    returns at once, so producers (`elaborate()`) and writers can both call it without doing the work twice.
    """
    key = id(netlist)  # key by identity instead of hash (cheaper)
    if key in _validated:
        return
    violations = check(netlist)
    if violations:
        raise ValidationError(violations)
    if isinstance(netlist, Netlist):
        _validated.add(key)
        weakref.finalize(netlist, _validated.discard, key)


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
    (Connection, "port"), (SignalRef, "signal"), (ParamDecl, "name"), (ParamValue, "name"), (ParamRef, "name"),
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
        if (cls, name) in _NAMES and not is_identifier(value):
            self.add("F-2", where, f"{value!r} is not an identifier ({IDENTIFIER})", cell, instance)
        elif cls is Range and value < 0:
            self.add("F-3", where, f"range index {value} is negative", cell, instance)
        elif cls is NoConnect and value < 1:
            self.add("F-3", where, f"width {value} is less than 1", cell, instance)
        elif cls is Number and value.is_finite() and value < 0:
            self.add("F-3", where, f"number {value} is negative (write a negation instead)", cell, instance)
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
    """N-1 to N-4 (names), D-1, D-2 (references), C-1 to C-5 (connections) and A-1 to A-5 (parameters), on a
    netlist that passes every field rule."""

    def __init__(self, netlist: Netlist):
        super().__init__()
        self.netlist = netlist
        # Cell name -> position in `Netlist.cells` (the first one, if names clash).
        self.position: dict[str, int] = {}

    def run(self) -> list[Violation]:
        self.names()
        self.refs()
        self.conns()
        self.params()
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

    def conns(self) -> None:
        """C-1 to C-5, for every instance whose reference is sound (D-1, D-2), to avoid follow-up noise."""
        for here, cell in enumerate(self.netlist.cells):
            if not isinstance(cell, Subckt):
                continue
            cell_nets = nets(cell)
            for inst in cell.instances:
                pos = self.position.get(inst.cell)
                if pos is not None and pos < here:
                    self.instance_conns(cell, cell_nets, inst, self.netlist.cells[pos])

    def instance_conns(self, cell: Subckt, cell_nets: dict[str, Signal], inst: Instance, target: Cell) -> None:
        """C-1 for one instance, then C-2 to C-5 for each of its connections."""
        where = f"cell {cell.name}, instance {inst.name}"
        ports = {port.name: port for port in target.ports}
        seen: set[str] = set()
        for conn in inst.connections:
            if conn.port not in ports:
                self.add("C-1", where, f"{target.name!r} has no port {conn.port!r}", cell.name, inst.name)
            elif conn.port in seen:
                self.add("C-1", where, f"port {conn.port!r} is connected more than once", cell.name, inst.name)
            else:
                seen.add(conn.port)
                self.pieces(f"{where}, port {conn.port}", cell, cell_nets, inst, ports[conn.port], conn.pieces)
        for name in ports:
            if name not in seen:
                self.add("C-1", where, f"port {name!r} of {target.name!r} is not connected", cell.name, inst.name)

    def pieces(
        self,
        where: str,
        cell: Subckt,
        cell_nets: dict[str, Signal],
        inst: Instance,
        port: Signal,
        pieces: tuple[Piece, ...],
    ) -> None:
        """C-2 and C-3 per piece, then C-4 (total width) and C-5 (canonical form) if every piece is sound."""
        sound = True
        for piece in pieces:
            if not isinstance(piece, SignalRef):
                continue
            signal = cell_nets.get(piece.signal)
            if signal is None:
                self.add(
                    "C-2", where, f"{piece.signal!r} is not a port or signal of {cell.name!r}", cell.name, inst.name
                )
                sound = False
            elif piece.range is not None and signal.range is None:
                self.add("C-3", where, f"{piece.signal!r} is a scalar, so it takes no range", cell.name, inst.name)
                sound = False
            elif piece.range is not None and not _within(piece.range, signal.range):
                message = f"{_fmt_piece(piece)} lies outside the declared {_fmt_range(piece.signal, signal.range)}"
                self.add("C-3", where, message, cell.name, inst.name)
                sound = False
        if not sound:
            return
        total = sum(_piece_width(piece, cell_nets) for piece in pieces)
        if total != width(port.range):
            message = f"connects {total} bit(s), but port {port.name!r} has {width(port.range)}"
            self.add("C-4", where, message, cell.name, inst.name)
            return
        canonical = canonical_pieces(bits(pieces, cell_nets), cell_nets)
        if canonical != pieces:
            message = f"pieces are not canonical: write {', '.join(_fmt_piece(p) for p in canonical)}"
            self.add("C-5", where, message, cell.name, inst.name)

    def params(self) -> None:
        """A-5 for every declaration, then A-1 to A-4 for every instance whose reference is sound."""
        for here, cell in enumerate(self.netlist.cells):
            if not isinstance(cell, Subckt):
                continue
            earlier: set[str] = set()
            for decl in cell.params:
                where = f"cell {cell.name}, parameter {decl.name}"
                self.scope("A-5", where, decl.default, earlier, "parameters declared earlier", cell.name, None)
                earlier.add(decl.name)
            own = {decl.name for decl in cell.params}
            for inst in cell.instances:
                pos = self.position.get(inst.cell)
                if pos is not None and pos < here:
                    self.instance_params(cell, own, inst, self.netlist.cells[pos])

    def instance_params(self, cell: Subckt, own: set[str], inst: Instance, target: Cell) -> None:
        """
        A-1 to A-4 for one instance. `own` are the parameters of the containing cell. An `External` target is open:
        it declares no parameters, and any may be set, as a number or a text (no A-1, no A-3).
        """
        where = f"cell {cell.name}, instance {inst.name}"
        closed = isinstance(target, Subckt)
        decls = {decl.name: decl for decl in target.params} if closed else {}
        given: set[str] = set()
        scope = f"parameters of {cell.name!r}"
        for value in inst.params:
            pwhere = f"{where}, parameter {value.name}"
            if value.name in given:
                self.add("A-2", pwhere, "parameter is set more than once", cell.name, inst.name)
                continue
            given.add(value.name)
            decl = decls.get(value.name)
            if decl is None and closed:
                self.add("A-1", pwhere, f"{target.name!r} declares no parameter {value.name!r}", cell.name, inst.name)
            elif closed and not isinstance(value.value, Expression):
                message = f"a subckt parameter is a number, not the text {value.value!r}"
                self.add("A-3", pwhere, message, cell.name, inst.name)
            else:
                self.scope("A-4", pwhere, value.value, own, scope, cell.name, inst.name)

    def scope(
        self, rule: str, where: str, value: Value, allowed: set[str], scope: str, cell: str, instance: str | None
    ) -> None:
        """A-4, A-5: an expression only refers to the parameters in `allowed`."""
        if not isinstance(value, Expression):
            return
        outside = [name for name in param_refs(value) if name not in allowed]
        if outside:
            self.add(rule, where, f"refers to {', '.join(outside)}, but may only use {scope}", cell, instance)

    def unique(self, rule: str, where: str, what: str, names: list[str], cell: str) -> None:
        seen: set[str] = set()
        for name in names:
            if name in seen:
                self.add(rule, where, f"{what} name {name!r} is used more than once", cell)
            seen.add(name)


def _nets(cell: Cell) -> tuple[Signal, ...]:
    """Every net of a cell, duplicates kept (for N-2): its ports, plus the internal signals of a `Subckt`."""
    return cell.ports + cell.signals if isinstance(cell, Subckt) else cell.ports


def _within(r: Range, declared: Range | None) -> bool:
    if declared is None:
        return False
    low, high = sorted((declared.msb, declared.lsb))
    return low <= r.msb <= high and low <= r.lsb <= high


def _piece_width(piece: Piece, cell_nets: dict[str, Signal]) -> int:
    if isinstance(piece, NoConnect):
        return piece.width
    return width(piece.range if piece.range is not None else cell_nets[piece.signal].range)


def _fmt_range(name: str, r: Range | None) -> str:
    return name if r is None else f"{name}<{r.msb}:{r.lsb}>"


def _fmt_piece(piece: Piece) -> str:
    if isinstance(piece, NoConnect):
        return f"NoConnect({piece.width})"
    return _fmt_range(piece.signal, piece.range)


def _fmt_bit(bit: NetBit) -> str:
    return bit.signal if bit.index is None else f"{bit.signal}<{bit.index}>"


# Warnings (spec 6.4)


def lint(netlist: Netlist) -> list[Violation]:
    """Floating-net warnings W-1 to W-3 of a valid netlist."""
    warnings: list[Violation] = []
    for cell in netlist.cells:
        if not isinstance(cell, Subckt):
            continue
        cell_nets = nets(cell)
        count = {bit: 0 for signal in cell_nets.values() for bit in signal_bits(signal)}
        for inst in cell.instances:
            for conn in inst.connections:
                for bit in bits(conn.pieces, cell_nets):
                    if bit is not OPEN:
                        count[bit] += 1
        where = f"cell {cell.name}"
        for port in cell.ports:
            for bit in signal_bits(port):
                if count[bit] == 0:
                    message = f"port bit {_fmt_bit(bit)} is not used inside the cell"
                    warnings.append(Violation(rule="W-2", where=where, message=message, cell=cell.name))
        for signal in cell.signals:
            signal_count = [count[bit] for bit in signal_bits(signal)]
            if not any(signal_count):
                message = f"signal {signal.name!r} is not connected to anything"
                warnings.append(Violation(rule="W-1", where=where, message=message, cell=cell.name))
                continue
            for bit, n in zip(signal_bits(signal), signal_count, strict=True):
                if n < 2:
                    message = f"net bit {_fmt_bit(bit)} is connected {n} time(s), so it floats"
                    warnings.append(Violation(rule="W-3", where=where, message=message, cell=cell.name))
    return warnings
