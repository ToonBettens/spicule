"""Cells and instances.

A subckt is a class deriving from `h.Subckt`, and the class name is the cell name::

    class Inv(h.Subckt):
        vdd = h.Port()
        vss = h.Port()
        a = h.Port()
        y = h.Port()
        nfin = h.Param(default=2)
        mp = pch(nfin=2 * nfin)(d=y, g=a, s=vdd, b=vdd)
        mn = nch(nfin=nfin)(d=y, g=a, s=vss, b=vss)

Public names in the class body must be ports, signals, parameters or instances. Helpers start with `_`.

Every cell is instantiated with two calls, parameters first and then connections, so a port and a parameter may share
a name::

    dut = Inv(nfin=4)(vdd=vdd, vss=gnd, a=a, y=y)
"""

from typing import Any

from spicule.hdl.nets import Connectable, Port, Signal
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

    def __call__(self, **params: Any) -> CellCall:
        return CellCall(self, self.check_params(params, caller()))


class CellCall:
    """A cell with parameter values, made by calling a cell. Calling it with connections gives an `Instance`."""

    def __init__(self, cell: CellInfo, params: dict[str, HdlValue]):
        self.source = caller()
        self.cell = cell
        self.params = params

    def __call__(self, **conns: Any) -> Instance:
        inst = Instance(self.cell, self.params)
        inst.connect(**conns)
        return inst

    def __repr__(self) -> str:
        return f"CellCall({self.cell.name})"


class Instance:
    """
    An instance of a cell inside a subckt, made by calling a `CellCall`. Its fields start with `_`, so that ports can
    become attributes later.
    """

    def __init__(self, cell: CellInfo, params: dict[str, HdlValue]):
        self._source = caller()
        self._cell = cell
        self._params = dict(params)
        self._conns: dict[str, tuple[Connectable, Source | None]] = {}
        self._name: str | None = None
        self._parent: object | None = None

    def __set_name__(self, owner: object, name: str) -> None:
        if self._parent is not None and self._parent is not owner:
            raise HdlError(f"instance {self._name!r} already belongs to {self._parent}", self._source)
        if self._name is not None and self._name != name:
            raise HdlError(f"instance {self._name!r} can't also be named {name!r}; create a new one", self._source)
        self._name = check_identifier(name, "instance name", self._source)
        self._parent = owner

    def connect(self, **conns: Any) -> Instance:
        """Connect ports by keyword. Returns the instance."""
        source = caller()
        for port_name, target in conns.items():
            self._connect(port_name, target, source)
        return self

    def _connect(self, port_name: str, target: Any, source: Source | None) -> None:
        cell = self._cell
        port = cell.ports.get(port_name)
        if port is None:
            hint = "; parameters go in the first call: cell(params)(ports)" if port_name in cell.params else ""
            known = ", ".join(cell.ports) or "none"
            raise HdlError(f"{cell.name} has no port {port_name!r} (ports: {known}){hint}", source)
        if port_name in self._conns:
            raise HdlError(f"port {port_name!r} is already connected", source, self._conns[port_name][1])
        if not isinstance(target, Connectable):
            raise HdlError(f"port {port_name!r} of {cell.name} can't be connected to {target!r}", source)
        if target.width is not None and target.width != port.width:
            raise HdlError(
                f"port {port_name!r} of {cell.name} is {port.width} bit(s) wide, the connection is {target.width}",
                source,
            )
        self._conns[port_name] = (target, source)

    def __repr__(self) -> str:
        return f"Instance({self._name or '?'} of {self._cell.name})"


# --- Subckts ---


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

    def __call__(cls, **params: Any) -> CellCall:
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
