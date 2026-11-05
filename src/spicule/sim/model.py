"""A simulation: a circuit, and what to do with it. The rules are in docs/sim-spec.md.

Frozen dataclasses, like the IR. Spectre owns the names of analyses and of their parameters, so analyses and options
are open: any parameter can be given. Their constructors take Python values and hold exact ones, so a value is a number
or `ir.Expression` (an `ir.Expression`), a text, or a list of those. A float goes through its shortest text: `1.6e-08`
is exactly 16e-9.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from spicule.ir import Expression, ExpressionError, Netlist, ParamDecl, ParamValue, Subckt, Value, number

#: A parameter of an analysis or of the options.
type SimValue = Value | tuple[Value, ...]


class SimulationError(ValueError):
    """A simulation that breaks a rule (`sim-spec.md`), or a value it can't hold."""


@dataclass(frozen=True, slots=True)
class Param:
    """A parameter of an analysis or of the options."""

    name: str
    value: SimValue


@dataclass(frozen=True, slots=True)
class Include:
    """A file to include, such as a PDK's models, with the section to read."""

    path: str
    section: str | None = None


@dataclass(frozen=True, slots=True)
class Raw:
    """Simulator text, written as it is. Nothing checks it, and every line of it is the simulator's."""

    text: str


@dataclass(frozen=True, slots=True, init=False)
class Options:
    """The simulator's options: `Options("opts", temp=27, reltol=1e-4)`."""

    name: str
    params: tuple[Param, ...]

    def __init__(self, name: str, /, **params: Any):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "params", _params(params))


@dataclass(frozen=True, slots=True, init=False)
class Analysis:
    """
    One analysis, by its name and the simulator's type: `Analysis("tr", "tran", stop=1e-9)`. A sweep or a Monte Carlo
    run holds the analyses it repeats in `children`.
    """

    name: str
    type: str
    params: tuple[Param, ...]
    children: tuple[Analysis | Raw, ...]

    def __init__(self, name: str, type: str, /, *, children: Sequence[Analysis | Raw] = (), **params: Any):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "params", _params(params))
        object.__setattr__(self, "children", _sequence(children, "children"))


@dataclass(frozen=True, slots=True, init=False)
class Simulation:
    """
    What to do with `netlist`: its cell `top` is the circuit, and its net `ground` is the reference node. `params`
    overrides parameters that `top` declares. `raw` lines come before the options, and a `Raw` in `analyses` keeps its
    place among them.
    """

    netlist: Netlist
    top: str
    ground: str
    params: tuple[ParamValue, ...]
    includes: tuple[Include, ...]
    options: Options | None
    saves: tuple[str, ...]
    raw: tuple[str, ...]
    analyses: tuple[Analysis | Raw, ...]

    def __init__(
        self,
        netlist: Netlist,
        *,
        top: str,
        ground: str,
        params: Mapping[str, Any] | None = None,
        includes: Sequence[Include] = (),
        options: Options | None = None,
        saves: Sequence[str] = (),
        raw: Sequence[str] = (),
        analyses: Sequence[Analysis | Raw] = (),
    ):
        object.__setattr__(self, "netlist", netlist)
        object.__setattr__(self, "top", top)
        object.__setattr__(self, "ground", ground)
        object.__setattr__(self, "params", _overrides(params or {}))
        object.__setattr__(self, "includes", _sequence(includes, "includes"))
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "saves", _sequence(saves, "saves"))
        object.__setattr__(self, "raw", _sequence(raw, "raw"))
        object.__setattr__(self, "analyses", _sequence(analyses, "analyses"))

    @property
    def top_cell(self) -> Subckt:
        """The cell `top`, of a valid simulation."""
        cell = next(cell for cell in self.netlist.cells if cell.name == self.top)
        assert isinstance(cell, Subckt)
        return cell

    @property
    def top_params(self) -> tuple[ParamDecl, ...]:
        """The parameters of the top cell in their order, with `params` in place of their defaults."""
        given = {param.name: param.value for param in self.params}
        params = []
        for decl in self.top_cell.params:
            value = given.get(decl.name, decl.default)
            assert isinstance(value, Expression)
            params.append(ParamDecl(name=decl.name, default=value))
        return tuple(params)

    @property
    def cells(self) -> tuple[Subckt, ...]:
        """The subcircuits below the top cell, leaves first. Other cells of the netlist aren't part of the simulation."""
        by_name = {cell.name: cell for cell in self.netlist.cells}
        needed: set[str] = set()
        pending = [self.top_cell]
        while pending:
            for inst in pending.pop().instances:
                target = by_name[inst.cell]
                if target.name not in needed:
                    needed.add(target.name)
                    if isinstance(target, Subckt):
                        pending.append(target)
        return tuple(cell for cell in self.netlist.cells if isinstance(cell, Subckt) and cell.name in needed)


def _sequence(items: Any, what: str) -> tuple:
    # A text is a sequence too, and `saves="out"` would save o, u and t.
    if not isinstance(items, list | tuple):
        raise SimulationError(f"{what}: expected a list, got {items!r}")
    return tuple(items)


def _params(params: Mapping[str, Any]) -> tuple[Param, ...]:
    return tuple(Param(name, _value(value, name)) for name, value in params.items())


def _overrides(params: Any) -> tuple[ParamValue, ...]:
    if not isinstance(params, Mapping):
        raise SimulationError(f"params: expected a dict of names and values, got {params!r}")
    for name, value in params.items():
        if isinstance(value, str):
            raise SimulationError(f"parameter {name}: a parameter of the top cell is a number, got the text {value!r}")
    return tuple(ParamValue(name=name, value=_number(value, name)) for name, value in params.items())


def _value(value: Any, what: str) -> SimValue:
    if isinstance(value, list | tuple):
        return tuple(_item(item, what) for item in value)
    return _item(value, what)


def _item(value: Any, what: str) -> Value:
    return value if isinstance(value, str) else _number(value, what)


def _number(value: Any, what: str) -> Expression:
    if isinstance(value, Expression):
        return value
    try:
        return number(Decimal(repr(value)) if isinstance(value, float) else value)
    except ExpressionError as error:
        raise SimulationError(f"parameter {what}: {error}") from None
