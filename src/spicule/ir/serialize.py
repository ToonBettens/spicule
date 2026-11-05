"""A `Netlist` as JSON text, and back (spec section 10).

The file follows the dataclasses field for field: the same names, and every field always written. A `kind` says which
one it is wherever a value can be one of several. Expressions are their text.
"""

import json
from typing import Any

from spicule.ir.expressions import ExpressionError, format_expression, parse_expression
from spicule.ir.model import (
    Cell,
    Connection,
    Element,
    Expression,
    External,
    Instance,
    Meta,
    Netlist,
    NoConnect,
    ParamDecl,
    ParamValue,
    Piece,
    Range,
    Signal,
    SignalRef,
    Subckt,
    Value,
)
from spicule.ir.validator import validate

#: What the file says it is: the format this module reads and writes, and its version.
FORMAT = "spicule.ir/1"


class FormatError(ValueError):
    """Text that isn't a netlist file: not JSON, another format or version, or the wrong shape."""


def to_json(netlist: Netlist) -> str:
    """`netlist` as JSON text. Only a valid netlist can be written."""
    validate(netlist)
    data = {"format": FORMAT, "cells": [_cell_data(cell) for cell in netlist.cells]}
    return json.dumps(data, indent=2) + "\n"


def from_json(text: str) -> Netlist:
    """
    The netlist in JSON `text`. Raises `FormatError` if the text doesn't have the shape of a netlist file, and
    `ValidationError` if it has, but the netlist breaks a rule.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise FormatError(f"not JSON: {error}") from error
    fields = _fields(data, "file", "format", "cells")
    if fields["format"] != FORMAT:
        raise FormatError(f"file: format is {fields['format']!r}, this reader knows {FORMAT!r}")
    netlist = Netlist(cells=_items(fields["cells"], "cells", _cell))
    validate(netlist)
    return netlist


# --- Writing ---


def _cell_data(cell: Cell) -> dict[str, Any]:
    if isinstance(cell, External):
        return {
            "kind": "external",
            "name": cell.name,
            "element": cell.element.value,
            "ports": [_signal_data(port) for port in cell.ports],
            "meta": _meta_data(cell.meta),
        }
    return {
        "kind": "subckt",
        "name": cell.name,
        "ports": [_signal_data(port) for port in cell.ports],
        "params": [{"name": decl.name, "default": _value_data(decl.default)} for decl in cell.params],
        "signals": [_signal_data(signal) for signal in cell.signals],
        "instances": [_instance_data(inst) for inst in cell.instances],
        "meta": _meta_data(cell.meta),
    }


def _instance_data(inst: Instance) -> dict[str, Any]:
    return {
        "name": inst.name,
        "cell": inst.cell,
        "connections": [
            {"port": conn.port, "pieces": [_piece_data(piece) for piece in conn.pieces]} for conn in inst.connections
        ],
        "params": [{"name": param.name, "value": _value_data(param.value)} for param in inst.params],
        "meta": _meta_data(inst.meta),
    }


def _signal_data(signal: Signal) -> dict[str, Any]:
    return {"name": signal.name, "range": _range_data(signal.range)}


def _piece_data(piece: Piece) -> dict[str, Any]:
    if isinstance(piece, NoConnect):
        return {"kind": "no_connect", "width": piece.width}
    return {"kind": "signal_ref", "signal": piece.signal, "range": _range_data(piece.range)}


def _range_data(r: Range | None) -> dict[str, int] | None:
    return None if r is None else {"msb": r.msb, "lsb": r.lsb}


def _value_data(value: Value) -> dict[str, str]:
    if isinstance(value, str):
        return {"kind": "text", "text": value}
    return {"kind": "expression", "text": format_expression(value)}


def _meta_data(meta: Meta) -> dict[str, str | None]:
    return {"origin": meta.origin}


# --- Reading ---


def _fields(data: Any, where: str, *names: str) -> dict[str, Any]:
    """`data` as an object with exactly these fields."""
    if not isinstance(data, dict):
        raise FormatError(f"{where}: expected an object, got {data!r}")
    missing = [name for name in names if name not in data]
    if missing:
        raise FormatError(f"{where}: missing field {missing[0]!r}")
    unknown = [name for name in data if name not in names]
    if unknown:
        raise FormatError(f"{where}: unknown field {unknown[0]!r}")
    return data


def _items(data: Any, where: str, read: Any) -> tuple:
    """A list, each item read with `read(item, where)`."""
    if not isinstance(data, list):
        raise FormatError(f"{where}: expected a list, got {data!r}")
    return tuple(read(item, f"{where}[{i}]") for i, item in enumerate(data))


def _kind(data: Any, where: str) -> str:
    if not isinstance(data, dict) or "kind" not in data:
        raise FormatError(f"{where}: expected an object with a 'kind', got {data!r}")
    return data["kind"]


def _cell(data: Any, where: str) -> Cell:
    kind = _kind(data, where)
    if kind == "external":
        fields = _fields(data, where, "kind", "name", "element", "ports", "meta")
        try:
            element = Element(fields["element"])
        except ValueError:
            raise FormatError(f"{where}: unknown element {fields['element']!r}") from None
        return External(
            name=fields["name"],
            element=element,
            ports=_items(fields["ports"], f"{where}.ports", _signal),
            meta=_meta(fields["meta"], f"{where}.meta"),
        )
    if kind == "subckt":
        fields = _fields(data, where, "kind", "name", "ports", "params", "signals", "instances", "meta")
        return Subckt(
            name=fields["name"],
            ports=_items(fields["ports"], f"{where}.ports", _signal),
            params=_items(fields["params"], f"{where}.params", _param_decl),
            signals=_items(fields["signals"], f"{where}.signals", _signal),
            instances=_items(fields["instances"], f"{where}.instances", _instance),
            meta=_meta(fields["meta"], f"{where}.meta"),
        )
    raise FormatError(f"{where}: unknown cell kind {kind!r}")


def _instance(data: Any, where: str) -> Instance:
    fields = _fields(data, where, "name", "cell", "connections", "params", "meta")
    return Instance(
        name=fields["name"],
        cell=fields["cell"],
        connections=_items(fields["connections"], f"{where}.connections", _connection),
        params=_items(fields["params"], f"{where}.params", _param_value),
        meta=_meta(fields["meta"], f"{where}.meta"),
    )


def _connection(data: Any, where: str) -> Connection:
    fields = _fields(data, where, "port", "pieces")
    return Connection(port=fields["port"], pieces=_items(fields["pieces"], f"{where}.pieces", _piece))


def _piece(data: Any, where: str) -> Piece:
    kind = _kind(data, where)
    if kind == "no_connect":
        return NoConnect(width=_fields(data, where, "kind", "width")["width"])
    if kind == "signal_ref":
        fields = _fields(data, where, "kind", "signal", "range")
        return SignalRef(signal=fields["signal"], range=_range(fields["range"], f"{where}.range"))
    raise FormatError(f"{where}: unknown piece kind {kind!r}")


def _signal(data: Any, where: str) -> Signal:
    fields = _fields(data, where, "name", "range")
    return Signal(name=fields["name"], range=_range(fields["range"], f"{where}.range"))


def _range(data: Any, where: str) -> Range | None:
    if data is None:
        return None
    fields = _fields(data, where, "msb", "lsb")
    return Range(msb=fields["msb"], lsb=fields["lsb"])


def _param_decl(data: Any, where: str) -> ParamDecl:
    fields = _fields(data, where, "name", "default")
    default = _value(fields["default"], f"{where}.default")
    if not isinstance(default, Expression):
        raise FormatError(f"{where}.default: a subckt parameter is a number, got the text {default!r}")
    return ParamDecl(name=fields["name"], default=default)


def _param_value(data: Any, where: str) -> ParamValue:
    fields = _fields(data, where, "name", "value")
    return ParamValue(name=fields["name"], value=_value(fields["value"], f"{where}.value"))


def _value(data: Any, where: str) -> Value:
    kind = _kind(data, where)
    if kind not in ("expression", "text"):
        raise FormatError(f"{where}: unknown value kind {kind!r}")
    text = _fields(data, where, "kind", "text")["text"]
    if not isinstance(text, str):
        raise FormatError(f"{where}: expected text, got {text!r}")
    if kind == "text":
        return text
    try:
        return parse_expression(text)
    except ExpressionError as error:
        raise FormatError(f"{where}: {error}") from error


def _meta(data: Any, where: str) -> Meta:
    return Meta(origin=_fields(data, where, "origin")["origin"])
