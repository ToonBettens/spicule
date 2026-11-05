"""The JSON writer: follows the model field for field, with every field always written.

A `kind` says which one it is wherever a value can be one of several. Expressions are their text.
"""

import json
from typing import Any

from spicule.dialects.jsonio.syntax import NETLIST_FORMAT, SIMULATION_FORMAT
from spicule.ir import Cell, External, Instance, Meta, Netlist, NoConnect, Piece, Range, Signal, Value, validate
from spicule.ir.expressions import format_expression
from spicule.sim import Analysis, Param, Raw, Simulation, SimValue
from spicule.sim import validate as validate_simulation


def write(design: Netlist | Simulation) -> str:
    """`design` as JSON text. Only a valid netlist or simulation can be written."""
    if isinstance(design, Simulation):
        validate_simulation(design)
        return _text(_simulation_data(design))
    validate(design)
    return _text({"format": NETLIST_FORMAT, "cells": _cells_data(design)})


def _text(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _simulation_data(simulation: Simulation) -> dict[str, Any]:
    options = simulation.options
    return {
        "format": SIMULATION_FORMAT,
        "netlist": {"cells": _cells_data(simulation.netlist)},
        "top": simulation.top,
        "ground": simulation.ground,
        "params": [{"name": param.name, "value": _value_data(param.value)} for param in simulation.params],
        "includes": [{"path": include.path, "section": include.section} for include in simulation.includes],
        "options": None if options is None else {"name": options.name, "params": _params_data(options.params)},
        "saves": list(simulation.saves),
        "raw": list(simulation.raw),
        "analyses": [_statement_data(item) for item in simulation.analyses],
    }


def _statement_data(item: Analysis | Raw) -> dict[str, Any]:
    if isinstance(item, Raw):
        return {"kind": "raw", "text": item.text}
    return {
        "kind": "analysis",
        "name": item.name,
        "type": item.type,
        "params": _params_data(item.params),
        "children": [_statement_data(child) for child in item.children],
    }


def _params_data(params: tuple[Param, ...]) -> list[dict[str, Any]]:
    return [{"name": param.name, "value": _sim_value_data(param.value)} for param in params]


def _sim_value_data(value: SimValue) -> dict[str, Any]:
    if isinstance(value, tuple):
        return {"kind": "list", "items": [_value_data(item) for item in value]}
    return _value_data(value)


def _cells_data(netlist: Netlist) -> list[dict[str, Any]]:
    return [_cell_data(cell) for cell in netlist.cells]


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
