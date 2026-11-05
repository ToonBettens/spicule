"""Cells and instances.

A subckt is a class deriving from `h.Subckt`, and the class name is the cell name::

    class Inv(h.Subckt):
        vdd = h.Port()
        vss = h.Port()
        a = h.Port()
        y = h.Port()
        nfin = h.Param(2)
        mp = pch(nfin=2 * nfin)(d=y, g=a, s=vdd, b=vdd)
        mn = nch(nfin=nfin)(d=y, g=a, s=vss, b=vss)

Public names in the class body must be ports, signals, parameters or instances. Helpers start with `_`.

Every cell is instantiated with two calls, parameters first and then connections, so a port and a parameter may share
a name. Connections go by keyword, or by position in the cell's port order::

    dut = Inv(nfin=4)(vdd=vdd, vss=gnd, a=a, y=y)
    buf = Inv()(vdd, gnd, y, z)
"""

from itertools import count
from typing import Any

from spicule.hdl.nets import Concat, Connectable, Port, Signal
from spicule.hdl.params import HdlValue, Param, as_number
from spicule.hdl.source import HdlError, Source, caller, check_identifier

# --- Instantiation ---


class CellInfo:
    """What instances need to know about a cell: a subckt or an external cell."""

    name: str
    ports: dict[str, Port]
    params: dict[str, Param]
    source: Source | None

    def check_params(self, values: dict[str, Any], source: Source | None) -> dict[str, HdlValue]:
        """Check and convert the parameter values of an instance."""
        raise NotImplementedError

    def __call__(self, /, **params: Any) -> CellCall:
        return CellCall(self, self.check_params(params, caller()))


class CellCall:
    """
    A cell with parameter values, made by calling a cell. Calling it with connections gives an `Instance`, and it can
    be called any number of times. `params` and `preset` give a new `CellCall` with more filled in, so a template
    shared between instances never changes::

        _p = pch(l=16e-9).preset(b=vdd)
        mp0 = _p(d=y, g=a, s=vdd)
        mp1 = _p.params(nfin=4)(d=y, g=b, s=vdd)
    """

    def __init__(self, cell: CellInfo, values: dict[str, HdlValue], presets: _Connections | None = None):
        self.source = caller()
        self.cell = cell
        self.values = values
        self.presets = presets or {}

    def params(self, **values: Any) -> CellCall:
        """A new `CellCall` with these parameter values added. A value that was already set is overridden."""
        return CellCall(self.cell, self.values | self.cell.check_params(values, caller()), self.presets)

    def preset(self, **conns: Any) -> CellCall:
        """A new `CellCall` with these ports already connected. They can't be connected again."""
        return CellCall(self.cell, self.values, _connect(self.cell, self.presets, conns, caller()))

    def __call__(self, /, *conns: Any, **named: Any) -> Instance:
        """
        The instance, with these ports connected: by keyword, or by position in the cell's port order, mixable with
        keywords. A call that connects by position connects every port, and can't follow a preset.
        """
        source = caller()
        targets = {**_by_position(self.cell, self.presets, conns, named, source), **named}
        return Instance(self.cell, self.values, _connect(self.cell, self.presets, targets, source))

    def __repr__(self) -> str:
        return f"CellCall({self.cell.name})"


# Connected ports: the port name, what it connects to, and the line that connected it.
type _Connections = dict[str, tuple[Connectable, Source | None]]


def _connect(cell: CellInfo, done: _Connections, targets: dict[str, Any], source: Source | None) -> _Connections:
    """`done` plus these connections, if the cell has those ports, they are still free and the widths fit."""
    connected = dict(done)
    for port_name, target in targets.items():
        port = cell.ports.get(port_name)
        if port is None:
            hint = "; parameters go in the first call: cell(params)(ports)" if port_name in cell.params else ""
            known = ", ".join(cell.ports) or "none"
            raise HdlError(f"{cell.name} has no port {port_name!r} (ports: {known}){hint}", source)
        if port_name in connected:
            raise HdlError(f"port {port_name!r} is already connected", source, connected[port_name][1])
        conn = Concat(*target) if isinstance(target, tuple) else target
        if not isinstance(conn, Connectable):
            raise HdlError(f"port {port_name!r} of {cell.name} can't be connected to {conn!r}", source)
        if conn.width is not None and conn.width != port.width:
            raise HdlError(
                f"port {port_name!r} of {cell.name} is {port.width} bit(s) wide, the connection is {conn.width}",
                source,
            )
        connected[port_name] = (conn, source)
    return connected


def _by_position(
    cell: CellInfo, done: _Connections, conns: tuple, named: dict[str, Any], source: Source | None
) -> dict[str, Any]:
    """Positional connections by their port name, if together with `named` they connect every port."""
    if not conns:
        return {}
    ports = list(cell.ports)
    if done:
        raise HdlError(f"{cell.name}: connections by position need all ports free; use keywords here", source)
    if len(conns) > len(ports):
        raise HdlError(f"{cell.name} has {len(ports)} port(s) ({', '.join(ports)}), got {len(conns)}", source)
    by_position = dict(zip(ports, conns, strict=False))
    twice = [name for name in named if name in by_position]
    if twice:
        raise HdlError(f"{cell.name}: port {twice[0]!r} is connected by position and by keyword", source)
    missing = [name for name in ports if name not in by_position and name not in named]
    if missing:
        raise HdlError(
            f"{cell.name}: connections by position connect every port; missing: {', '.join(missing)}", source
        )
    return by_position


class Instance:
    """
    An instance of a cell inside a subckt, made by calling a `CellCall`. Its connections are fixed when it is made.
    """

    def __init__(self, cell: CellInfo, params: dict[str, HdlValue], conns: _Connections):
        self.source = caller()
        self.cell = cell
        self.params = dict(params)
        self.conns = conns
        self.name: str | None = None
        self.owner: object | None = None  # The subckt (class) it belongs to

    def __set_name__(self, owner: object, name: str) -> None:
        if self.owner is not None and self.owner is not owner:
            raise HdlError(f"instance {self.name!r} already belongs to {self.owner}", self.source)
        if self.name is not None and self.name != name:
            raise HdlError(f"instance {self.name!r} can't also be named {name!r}; create a new one", self.source)
        self.name = check_identifier(name, "instance name", self.source)
        self.owner = owner

    def __repr__(self) -> str:
        return f"Instance({self.name or '?'} of {self.cell.name})"


# --- Subckts ---

_serials = count()


def new_serial() -> int:
    """A number that grows with every call: it tells which subckts are newer than a moment (generators)."""
    return next(_serials)


class SubcktInfo(CellInfo):
    """The contents of a subckt class (`h.info(cls)`)."""

    def __init__(self, cls: SubcktMeta, name: str, source: Source | None):
        self.cls = cls
        self.name = name
        self.source = source
        self.ports: dict[str, Port] = {}
        self.signals: dict[str, Signal] = {}
        self.instances: dict[str, Instance] = {}
        self.params: dict[str, Param] = {}
        self.serial = new_serial()
        self.generated = False  # Named by a generator

    def check_params(self, values: dict[str, Any], source: Source | None) -> dict[str, HdlValue]:
        """Only declared parameters may be set, and they are numbers."""
        checked: dict[str, HdlValue] = {}
        for name, value in values.items():
            if name not in self.params:
                hint = "; ports go in the second call: cell(params)(ports)" if name in self.ports else ""
                known = ", ".join(self.params) or "none"
                raise HdlError(f"{self.name} has no parameter {name!r} (parameters: {known}){hint}", source)
            checked[name] = as_number(value, f"parameter {name} of {self.name}", source)
        return checked

    def add(self, name: str, value: Any, source: Source | None) -> None:
        if any(name in d for d in (self.ports, self.signals, self.instances, self.params)):
            raise HdlError(f"subckt {self.name} already has an attribute {name!r}", source)
        if isinstance(value, Port):
            self.ports[name] = value
        elif isinstance(value, Signal):
            self.signals[name] = value
        elif isinstance(value, Instance):
            self.instances[name] = value
        elif isinstance(value, Param):
            self.params[name] = value
        elif isinstance(value, CellCall):
            raise HdlError(
                f"subckt {self.name}: {name} = {value.cell.name}(...) has parameters but no connections; "
                f"call it again with the connections: {value.cell.name}(...)(port=net, ...)",
                value.source,
            )
        else:
            raise HdlError(
                f"subckt {self.name}: attribute {name!r} = {value!r} is not a Port, Signal, Instance or Param "
                f"(start helper names with '_' to keep them out of the subckt)",
                getattr(value, "source", None) or source,
            )

    def __repr__(self) -> str:
        return f"subckt {self.name}"


class _ClassBody(dict):
    """A class body that refuses a public name twice: `r0 = ...` a second time would silently lose a device."""

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self and not key.startswith("_"):
            raise HdlError(f"{key!r} is assigned twice in this subckt", caller())
        super().__setitem__(key, value)


class SubcktMeta(type):
    """Metaclass of `h.Subckt`: collects the class body into a `SubcktInfo` (`cls.__hdl__`)."""

    __hdl__: SubcktInfo

    @classmethod
    def __prepare__(mcls, name: str, bases: tuple[type, ...], /, **kwds: Any) -> _ClassBody:
        return _ClassBody()

    def __new__(mcls, clsname: str, bases: tuple[type, ...], ns: dict[str, Any]):
        source = caller()
        if not bases:  # h.Subckt itself
            return super().__new__(mcls, clsname, bases, ns)
        if bases != (Subckt,):
            raise HdlError(f"subckt {clsname} must derive from h.Subckt only; subckts can't be subclassed", source)
        name = check_identifier(clsname, "cell name", source)
        cls = super().__new__(mcls, clsname, bases, ns)  # Runs __set_name__ on the class body.
        info = SubcktInfo(cls, name, source)
        type.__setattr__(cls, "__hdl__", info)
        for key, value in ns.items():
            if not key.startswith("_"):  # Dunders and private helpers stay out.
                info.add(key, value, source)
        return cls

    def __setattr__(cls, name: str, value: Any) -> None:
        if name.startswith("_") or "__hdl__" not in cls.__dict__:
            type.__setattr__(cls, name, value)
            return
        cls.__hdl__.add(name, value, caller())
        value.__set_name__(cls, name)
        type.__setattr__(cls, name, value)

    def __delattr__(cls, name: str) -> None:
        raise HdlError(f"attributes can't be removed from subckt {cls.__name__}", caller())

    def __call__(cls, /, **params: Any) -> CellCall:
        if "__hdl__" not in cls.__dict__:
            raise HdlError("h.Subckt itself can't be instantiated; derive a subckt from it", caller())
        return cls.__hdl__(**params)

    def __repr__(cls) -> str:
        info = cls.__dict__.get("__hdl__")
        return f"<{info}>" if info else super().__repr__()


class Subckt(metaclass=SubcktMeta):
    """Base class of every subckt. See `spicule.hdl.subckt`."""


def new_subckt(name: str) -> SubcktMeta:
    """
    An empty subckt named `name`, to fill by assigning attributes, for contents that ordinary Python decides::

        m = h.new_subckt("inv_x4")
        m.vdd = h.Port()
    """
    return SubcktMeta(name, (Subckt,), {"__module__": __name__})


def info(subckt: object) -> SubcktInfo:
    """The `SubcktInfo` (ports, signals, instances, parameters) of a subckt class."""
    if not isinstance(subckt, SubcktMeta) or "__hdl__" not in subckt.__dict__:
        raise HdlError(f"{subckt!r} is not a subckt", caller())
    return subckt.__hdl__
