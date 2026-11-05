"""Helpers shared by the writers: errors, and net names per cell."""

from spicule.ir import Cell, Instance, Subckt
from spicule.ir.connections import OPEN, NetBit, bits, nets, signal_bits


class WriterError(ValueError):
    """A valid netlist that this dialect can't express (a keyword as a name, an unknown built-in, ...)."""


class NetNames:
    """The text name of every bit of one cell: bus bits spelled with `bus_format`, open bits as fresh nets."""

    def __init__(self, cell: Subckt, bus_format: str, ground: str | None = None):
        self.cell = cell
        self.bus_format = bus_format
        self.ground = ground
        self.names: dict[NetBit, str] = {}
        self.used: set[str] = set()
        for signal in nets(cell).values():
            for bit in signal_bits(signal):
                name = self.spell(bit)
                if name in self.used:
                    raise WriterError(f"cell {cell.name!r}: two nets are both spelled {name!r} with {bus_format!r}")
                self.names[bit] = name
                self.used.add(name)

    def spell(self, bit: NetBit) -> str:
        if self.ground is not None and bit == NetBit(self.ground, None):
            return "0"
        if bit.index is None:
            return bit.signal
        return self.bus_format.format(name=bit.signal, index=bit.index)

    def pins(self) -> list[str]:
        """The names of the cell's port bits, in pin order."""
        return [self.names[bit] for port in self.cell.ports for bit in signal_bits(port)]

    def nodes(self, inst: Instance, target: Cell) -> list[str]:
        """The names `inst` connects to, in the pin order of `target`. Each open bit gets a fresh net."""
        cell_nets = nets(self.cell)
        pieces = {conn.port: conn.pieces for conn in inst.connections}
        out = []
        for port in target.ports:
            for bit in bits(pieces[port.name], cell_nets):
                out.append(self.fresh(f"nc_{inst.name}_") if bit is OPEN else self.names[bit])
        return out

    def fresh(self, prefix: str) -> str:
        k = 0
        while f"{prefix}{k}" in self.used:
            k += 1
        name = f"{prefix}{k}"
        self.used.add(name)
        return name
