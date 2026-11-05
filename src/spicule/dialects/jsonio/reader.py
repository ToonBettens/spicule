"""The JSON reader: the writer's format, back to a validated netlist or simulation."""

import json
from typing import Any

from spicule.dialects.jsonio.syntax import NETLIST_FORMAT, SIMULATION_FORMAT, FormatError
from spicule.ir import (
    Cell,
    Connection,
    Element,
    Expression,
    ExpressionError,
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
    parse_expression,
    validate,
)
from spicule.sim import Analysis, Include, Options, Raw, Simulation, SimValue
from spicule.sim import validate as validate_simulation


def read(text: str) -> Netlist | Simulation:
    """
    The netlist or simulation in JSON `text`, as its `format` says. Raises `FormatError` if the text doesn't have the
    shape of such a file, `ValidationError` if a netlist breaks a rule, and `SimulationError` if a simulation does.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise FormatError(f"not JSON: {error}") from error
    if not isinstance(data, dict) or "format" not in data:
        raise FormatError(f"file: expected an object with a 'format', got {data!r}")
    if data["format"] == NETLIST_FORMAT:
        fields = _fields(data, "file", "format", "cells")
        netlist = Netlist(cells=_items(fields["cells"], "cells", _cell))
        validate(netlist)
        return netlist
    if data["format"] == SIMULATION_FORMAT:
        simulation = _simulation(data)
        validate_simulation(simulation)
        return simulation
    raise FormatError(
        f"file: format is {data['format']!r}, this reader knows {NETLIST_FORMAT!r}, {SIMULATION_FORMAT!r}"
    )


def _simulation(data: dict[str, Any]) -> Simulation:
    fields = _fields(
        data, "file", "format", "netlist", "top", "ground", "params", "includes", "options", "saves", "raw", "analyses"
    )
    netlist = _fields(fields["netlist"], "netlist", "cells")
    return Simulation(
        Netlist(cells=_items(netlist["cells"], "netlist.cells", _cell)),
        top=fields["top"],
        ground=fields["ground"],
        params=dict(_named(fields["params"], "params", _value)),
        includes=_items(fields["includes"], "includes", _include),
        options=None if fields["options"] is None else _options(fields["options"], "options"),
        saves=_items(fields["saves"], "saves", _text),
        raw=_items(fields["raw"], "raw", _text),
        analyses=_items(fields["analyses"], "analyses", _statement),
    )


def _include(data: Any, where: str) -> Include:
    fields = _fields(data, where, "path", "section")
    return Include(fields["path"], fields["section"])


def _options(data: Any, where: str) -> Options:
    fields = _fields(data, where, "name", "params")
    return Options(fields["name"], **_open_params(fields["params"], f"{where}.params"))


def _statement(data: Any, where: str) -> Analysis | Raw:
    kind = _kind(data, where)
    if kind == "raw":
        return Raw(_text(_fields(data, where, "kind", "text")["text"], f"{where}.text"))
    if kind == "analysis":
        fields = _fields(data, where, "kind", "name", "type", "params", "children")
        params = _open_params(fields["params"], f"{where}.params")
        if "children" in params:
            raise FormatError(f"{where}.params: 'children' can't be a parameter name")
        return Analysis(
            fields["name"],
            fields["type"],
            children=_items(fields["children"], f"{where}.children", _statement),
            **params,
        )
    raise FormatError(f"{where}: unknown statement kind {kind!r}")


def _open_params(data: Any, where: str) -> dict[str, SimValue]:
    """The parameters of an analysis or of the options, by name."""
    return dict(_named(data, where, _sim_value))


def _named(data: Any, where: str, read_value: Any) -> list[tuple[str, Any]]:
    """A list of `{name, value}`, each name once."""
    if not isinstance(data, list):
        raise FormatError(f"{where}: expected a list, got {data!r}")
    named: dict[str, Any] = {}
    for i, item in enumerate(data):
        fields = _fields(item, f"{where}[{i}]", "name", "value")
        name = fields["name"]
        if not isinstance(name, str):
            raise FormatError(f"{where}[{i}].name: expected text, got {name!r}")
        if name in named:
            raise FormatError(f"{where}: parameter {name!r} is there more than once")
        named[name] = read_value(fields["value"], f"{where}[{i}].value")
    return list(named.items())


def _sim_value(data: Any, where: str) -> SimValue:
    if _kind(data, where) == "list":
        return _items(_fields(data, where, "kind", "items")["items"], f"{where}.items", _value)
    return _value(data, where)


def _text(data: Any, where: str) -> str:
    if not isinstance(data, str):
        raise FormatError(f"{where}: expected text, got {data!r}")
    return data


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
