"""The validator: checks a `Simulation` against the rules of docs/sim-spec.md, after its netlist against the IR's."""

from typing import Any

from spicule.ir import Expression, Netlist, Subckt, is_identifier
from spicule.ir import validate as validate_netlist
from spicule.ir.connections import nets
from spicule.ir.expressions import param_refs
from spicule.sim.model import Analysis, Include, Options, Param, Raw, Simulation, SimulationError


def validate(simulation: Simulation) -> None:
    """Raise `SimulationError` at the first broken rule, or `ValidationError` if the netlist breaks one of its own."""
    if not isinstance(simulation, Simulation):
        raise SimulationError(f"expected a Simulation, got {type(simulation).__name__}")
    if not isinstance(simulation.netlist, Netlist):
        raise SimulationError(f"[S-1] netlist: expected a Netlist, got {type(simulation.netlist).__name__}")
    validate_netlist(simulation.netlist)
    top = _top(simulation)
    _ground(top, simulation.ground)
    _overrides(top, simulation)
    _includes(simulation.includes)
    if simulation.options is not None:
        _options(simulation.options)
    for save in simulation.saves:
        if not isinstance(save, str) or not save or len(save.split()) != 1:
            raise SimulationError(f"[S-7] save: expected one name, got {save!r}")
    for line in simulation.raw:
        _raw(line)
    _statements(simulation.analyses, "analyses")
    names = [inst.name for inst in top.instances]
    if simulation.options is not None:
        names.append(simulation.options.name)
    _unique(names + [item.name for item in simulation.analyses if isinstance(item, Analysis)], "the top level")


def _top(simulation: Simulation) -> Subckt:
    for cell in simulation.netlist.cells:
        if cell.name == simulation.top:
            if isinstance(cell, Subckt):
                return cell
            break
    raise SimulationError(f"[S-1] top {simulation.top!r} is not a subcircuit of the netlist")


def _ground(top: Subckt, ground: Any) -> None:
    net = nets(top).get(ground) if isinstance(ground, str) else None
    if net is None or net.range is not None:
        raise SimulationError(f"[S-2] ground {ground!r} is not a scalar net of {top.name!r}")


def _overrides(top: Subckt, simulation: Simulation) -> None:
    """Each override is of a declared parameter, and refers to the ones declared before it, as a default does."""
    declared = [decl.name for decl in top.params]
    for param in simulation.params:
        if param.name not in declared:
            known = ", ".join(declared) or "none"
            raise SimulationError(f"[S-3] parameter {param.name!r} is not declared by {top.name!r} (declared: {known})")
        assert isinstance(param.value, Expression)
        earlier = declared[: declared.index(param.name)]
        outside = [name for name in param_refs(param.value) if name not in earlier]
        if outside:
            raise SimulationError(
                f"[S-3] parameter {param.name!r} refers to {', '.join(outside)}, but may only use parameters declared "
                f"earlier"
            )


def _includes(includes: tuple[Include, ...]) -> None:
    for include in includes:
        if not isinstance(include, Include):
            raise SimulationError(f"[S-6] includes: expected an Include, got {include!r}")
        if not isinstance(include.path, str) or not include.path or "\n" in include.path:
            raise SimulationError(f"[S-6] include: {include.path!r} is not a path")
        if include.section is not None and not is_identifier(include.section):
            raise SimulationError(f"[S-6] include {include.path!r}: section {include.section!r} is not a name")


def _options(options: Any) -> None:
    if not isinstance(options, Options):
        raise SimulationError(f"[S-4] options: expected Options, got {options!r}")
    _name(options.name, "options")
    _params(options.params, f"options {options.name}")


def _statements(items: tuple[Analysis | Raw, ...], where: str) -> None:
    """Every analysis, with its children, and the `Raw` among them."""
    for item in items:
        if isinstance(item, Raw):
            _raw(item.text)
        elif isinstance(item, Analysis):
            _name(item.name, "analysis")
            _name(item.type, f"analysis {item.name}: type")
            _params(item.params, f"analysis {item.name}")
            _statements(item.children, f"analysis {item.name}")
            _unique([child.name for child in item.children if isinstance(child, Analysis)], f"analysis {item.name}")
        else:
            raise SimulationError(f"[S-4] {where}: expected an Analysis or a Raw, got {item!r}")


def _params(params: tuple[Param, ...], where: str) -> None:
    for param in params:
        _name(param.name, f"{where}: parameter")
        if isinstance(param.value, tuple) and not param.value:
            raise SimulationError(f"[S-4] {where}, parameter {param.name}: a list has at least one value")


def _raw(text: Any) -> None:
    if not isinstance(text, str) or not text.strip():
        raise SimulationError(f"[S-7] raw: expected text, got {text!r}")


def _name(name: Any, where: str) -> None:
    if not is_identifier(name):
        raise SimulationError(f"[S-4] {where}: {name!r} is not a name")


def _unique(names: list[str], where: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise SimulationError(f"[S-5] {where}: the name {name!r} is used more than once")
        seen.add(name)
