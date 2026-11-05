"""Elaboration: subckts to a validated `ir.Netlist`.

`elaborate(*tops)` leaves the subckts unchanged. It

1. collects every cell the tops use, leaves first, and refuses cycles,
2. refuses two different cells with one name, since names are final in the IR,
3. converts connections to canonical pieces and parameter values to expressions,
4. fills `meta.origin` of cells and instances with `file:line`,
5. validates the netlist.

Problems raise `HdlError` with the Python lines involved, including rules the netlist breaks.
"""

import warnings
from collections.abc import Collection
from pathlib import Path
from typing import Any

from spicule import ir
from spicule.hdl.external import External
from spicule.hdl.nets import Connectable
from spicule.hdl.params import HdlValue, Param, refs, value_ir
from spicule.hdl.source import HdlError, HdlWarning, Source, caller
from spicule.hdl.subckt import CellInfo, Instance, SubcktInfo, info


def elaborate(*tops: Any, root: str | Path | None = None, lint: bool = False) -> ir.Netlist:
    """
    The validated netlist of the subckts `tops` and every cell they use, leaves first.

    - `root` is the directory `meta.origin` paths are relative to. Without it, each file's nearest directory with
      a `pyproject.toml`, or else the directory above its top-level package.
    - `lint=True` also warns (`HdlWarning`) about floating nets, at the lines of their cells.
    """
    if not tops:
        raise HdlError("elaborate() needs at least one subckt", caller())
    cells = _collect([info(top) for top in tops])
    _check_names(cells)
    base = Path(root) if root is not None else None
    netlist = ir.Netlist(cells=tuple(_cell(cell, base) for cell in cells))
    by_name = {cell.name: cell for cell in cells}
    try:
        ir.validate(netlist)
    except ir.ValidationError as error:
        lines = [f"the netlist breaks {len(error.violations)} rule(s):"]
        for v in error.violations:
            lines.append(f"  {v}")
            lines.extend(f"    at {s}" for s in _sources_of(by_name, v.cell, v.instance))
        raise HdlError("\n".join(lines)) from error
    if lint:
        for w in ir.lint(netlist):
            at = "".join(f"\n  at {s}" for s in _sources_of(by_name, w.cell, w.instance))
            warnings.warn(f"{w}{at}", HdlWarning, stacklevel=2)
    return netlist


def _sources_of(cells: dict[str, CellInfo], cell: str | None, instance: str | None) -> list[Source]:
    found = cells.get(cell) if cell is not None else None
    if found is None:
        return []
    if instance is not None and isinstance(found, SubcktInfo) and instance in found.instances:
        source = found.instances[instance].source
    else:
        source = found.source
    return [source] if source is not None else []


# --- Collecting ---


def _collect(tops: list[SubcktInfo]) -> list[CellInfo]:
    """Every cell the tops use, each once, leaves first."""
    cells: list[CellInfo] = []
    done: set[CellInfo] = set()
    stack: list[SubcktInfo] = []

    def visit(cell: SubcktInfo) -> None:
        if cell in done:
            return
        if cell in stack:
            chain = " -> ".join(s.name for s in [*stack[stack.index(cell) :], cell])
            raise HdlError(f"the subckt hierarchy has a cycle: {chain}", cell.source)
        stack.append(cell)
        for inst in cell.instances.values():
            target = inst.cell
            if isinstance(target, SubcktInfo):
                visit(target)
            elif target not in done:
                done.add(target)
                cells.append(target)
        stack.pop()
        done.add(cell)
        cells.append(cell)

    for top in tops:
        visit(top)
    return cells


def _check_names(cells: list[CellInfo]) -> None:
    """Different cells need different names: names in the netlist are final."""
    seen: dict[str, CellInfo] = {}
    for cell in cells:
        other = seen.setdefault(cell.name, cell)
        if other is not cell:
            raise HdlError(
                f"two different cells are both called {cell.name!r}; rename one of them",
                other.source,
                cell.source,
            )


# --- Cells ---


def _origin(source: Source | None, root: Path | None) -> str | None:
    return None if source is None else source.text(root)


def _cell(cell: CellInfo, root: Path | None) -> ir.Cell:
    if isinstance(cell, External):
        return cell.to_ir(_origin(cell.source, root))
    assert isinstance(cell, SubcktInfo)
    return _SubcktBuilder(cell, root).build()


class _SubcktBuilder:
    def __init__(self, info: SubcktInfo, root: Path | None):
        self.info = info
        self.root = root
        self.nets = {name: net.to_decl() for name, net in (*info.ports.items(), *info.signals.items())}

    def build(self) -> ir.Subckt:
        info = self.info
        earlier: list[Param] = []
        for decl in info.params.values():
            what = f"the default of {decl.name}"
            self.check_refs(decl.default, earlier, what, decl.source, "parameters declared before it")
            earlier.append(decl)
        return ir.Subckt(
            name=info.name,
            ports=tuple(port.to_decl() for port in info.ports.values()),
            params=tuple(decl.to_decl() for decl in info.params.values()),
            signals=tuple(signal.to_decl() for signal in info.signals.values()),
            instances=tuple(self.instance(name, inst) for name, inst in info.instances.items()),
            meta=ir.Meta(origin=_origin(info.source, self.root)),
        )

    def instance(self, name: str, inst: Instance) -> ir.Instance:
        target = inst.cell
        connections = []
        for port_name, port in target.ports.items():
            if port_name not in inst.conns:
                raise HdlError(
                    f"port {port_name!r} of instance {name} ({target.name}) is not connected; "
                    f"connect it, or use h.NoConn() for a pin left open on purpose",
                    inst.source,
                )
            conn, source = inst.conns[port_name]
            self.check_owners(conn, source)
            bits = ir.connections.bits(conn.to_ir(port.width), self.nets)
            pieces = ir.connections.canonical_pieces(bits, self.nets)
            connections.append(ir.Connection(port=port_name, pieces=pieces))
        params = []
        for pname, value in inst.params.items():
            what = f"parameter {pname} of instance {name}"
            self.check_refs(value, self.info.params.values(), what, inst.source, f"parameters of {self.info.name}")
            params.append(ir.ParamValue(name=pname, value=value_ir(value)))
        return ir.Instance(
            name=name,
            cell=target.name,
            connections=tuple(connections),
            params=tuple(params),
            meta=ir.Meta(origin=_origin(inst.source, self.root)),
        )

    def check_owners(self, conn: Connectable, source: Source | None) -> None:
        """A connection only uses nets of this subckt: a net of another one might share a name."""
        for net in conn.nets():
            if net.owner is not self.info.cls:
                owner = getattr(net.owner, "__hdl__", None) or "no subckt"
                raise HdlError(f"{net} belongs to {owner}, not to subckt {self.info.name}", source, net.source)

    def check_refs(
        self, value: HdlValue, allowed: Collection[Param], what: str, source: Source | None, scope: str
    ) -> None:
        for ref in refs(value):
            if ref not in allowed:
                owner = getattr(ref.owner, "__hdl__", None) or "no subckt"
                raise HdlError(f"{what} uses parameter {ref.name or '?'} of {owner}; it may only use {scope}", source)
