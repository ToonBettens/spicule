"""The JSON writer: follows the model field for field, with every field always written.

A `kind` says which one it is wherever a value can be one of several. Expressions are their text.
"""

import json
from typing import Any

from spicule.dialects.jsonio.syntax import FORMAT
from spicule.ir import Cell, External, Instance, Meta, Netlist, NoConnect, Piece, Range, Signal, Value, validate
from spicule.ir.expressions import format_expression


def write(netlist: Netlist) -> str:
    """`netlist` as JSON text. Only a valid netlist can be written."""
    validate(netlist)
    data = {"format": FORMAT, "cells": [_cell_data(cell) for cell in netlist.cells]}
    return json.dumps(data, indent=2) + "\n"


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
