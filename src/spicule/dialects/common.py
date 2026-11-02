"""Helpers shared by the writers: errors, which cells to write, and net names per cell."""

import re

from spicule.ir import Cell, Instance, Netlist, Subckt
from spicule.ir.connections import OPEN, Bit, NetBit, nets, signal_bits

#: An identifier, for deciding whether a string value needs quotes.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WriterError(ValueError):
    """A valid netlist that this dialect can't express (a keyword as a name, an unknown built-in, ...)."""


def cells_to_write(netlist: Netlist, top: str | None) -> tuple[list[Subckt], Subckt | None]:
    """
    The subcircuits to define, leaves first, and the top cell. Without `top`: every `Subckt`, no top. With `top`:
    the `Subckt`s below it, and the top cell itself, whose contents go at the top level.
    """
    by_name: dict[str, Cell] = {cell.name: cell for cell in netlist.cells}
    if top is None:
        return [cell for cell in netlist.cells if isinstance(cell, Subckt)], None
    top_cell = by_name.get(top)
    if not isinstance(top_cell, Subckt):
        raise WriterError(f"top {top!r} is not a subcircuit of the netlist")
    needed: set[str] = set()
    pending = [top_cell]
    while pending:
        for inst in pending.pop().instances:
            target = by_name[inst.cell]
            if target.name not in needed:
                needed.add(target.name)
                if isinstance(target, Subckt):
                    pending.append(target)
    defined = [c for c in netlist.cells if isinstance(c, Subckt) and c.name in needed and c.name != top]
    return defined, top_cell


def check_ground(top_cell: Subckt | None, ground: str | None) -> None:
    """Check the shared writer argument `ground`: a scalar net of the top cell, so it needs a top."""
    if ground is None:
        return
    if top_cell is None:
        raise WriterError("ground needs a top cell")
    net = nets(top_cell).get(ground)
    if net is None or net.range is not None:
        raise WriterError(f"ground {ground!r} is not a scalar net of {top_cell.name!r}")


class NetNames:
    """The text name of every bit of one cell: bus bits spelled with `bus_format`, open bits as fresh nets."""

    def __init__(self, cell: Subckt, bus_format: str, ground: str | None = None):
        self.cell = cell
        self.bus_format = bus_format
        self.ground = ground
        self.names: dict[NetBit, str] = {}
        for signal in nets(cell).values():
            for bit in signal_bits(signal):
                name = self.spell(bit)
                if name in self.names.values():
                    raise WriterError(f"cell {cell.name!r}: two nets are both spelled {name!r} with {bus_format!r}")
                self.names[bit] = name
        self.used = set(self.names.values())

    def spell(self, bit: NetBit) -> str:
        if self.ground is not None and bit == NetBit(self.ground, None):
            return "0"
        if bit.index is None:
            return bit.signal
        return self.bus_format.format(name=bit.signal, index=bit.index)

    def of(self, bits: list[Bit], inst: Instance) -> list[str]:
        """Names for the bits of one connection of `inst`. Each open bit gets a fresh net."""
        out = []
        for bit in bits:
            if bit is OPEN:
                out.append(self.fresh(f"nc_{inst.name}_"))
            else:
                out.append(self.names[bit])
        return out

    def fresh(self, prefix: str) -> str:
        k = 0
        while f"{prefix}{k}" in self.used:
            k += 1
        name = f"{prefix}{k}"
        self.used.add(name)
        return name
