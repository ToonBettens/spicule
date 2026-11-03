"""Bits and the canonical form of connections.

A connection is a list of pieces in expansion order. These helpers flatten pieces into bits and rebuild the one
canonical piece list for a list of bits. A piece without range means the whole signal, so expanding it needs the
declared nets of the containing cell.
"""

import dataclasses
from collections.abc import Iterable, Mapping
from typing import NamedTuple

from spicule.ir.model import Cell, Instance, Netlist, NoConnect, Piece, Range, Signal, SignalRef, Subckt


class NetBit(NamedTuple):
    """One bit of a port or internal signal. `index` is None for a scalar signal."""

    signal: str
    index: int | None


#: One deliberately open bit.
OPEN = None

#: One bit of a connection: a net bit or `OPEN`.
Bit = NetBit | None


def indices(r: Range) -> list[int]:
    """Bit indices of a range in expansion order: <3:0> is [3, 2, 1, 0], <0:3> is [0, 1, 2, 3]."""
    step = -1 if r.msb >= r.lsb else 1
    return list(range(r.msb, r.lsb + step, step))


def width(r: Range | None) -> int:
    """Width of a signal or signal reference with this range: 1 without range."""
    return 1 if r is None else abs(r.msb - r.lsb) + 1


def nets(cell: Cell) -> dict[str, Signal]:
    """Every net of a cell by name: its ports, plus the internal signals of a `Subckt`."""
    signals = cell.ports + cell.signals if isinstance(cell, Subckt) else cell.ports
    return {s.name: s for s in signals}


def signal_bits(signal: Signal) -> list[NetBit]:
    """All bits of a signal, in expansion order."""
    if signal.range is None:
        return [NetBit(signal.name, None)]
    return [NetBit(signal.name, i) for i in indices(signal.range)]


def bits(pieces: Iterable[Piece], cell_nets: Mapping[str, Signal]) -> list[Bit]:
    """Flatten pieces into bits, in expansion order. A signal reference without range takes the whole declared signal."""
    out: list[Bit] = []
    for piece in pieces:
        match piece:
            case NoConnect(width=w):
                out.extend([OPEN] * w)
            case SignalRef(signal=name, range=Range() as r):
                out.extend(NetBit(name, i) for i in indices(r))
            case SignalRef(signal=name):
                out.extend(signal_bits(cell_nets[name]))
    return out


def canonical_pieces(bit_list: list[Bit], cell_nets: Mapping[str, Signal]) -> tuple[Piece, ...]:
    """
    The canonical pieces for a list of bits (spec 6.3): scanning left to right, each piece is the longest run of
    one bus stepping by +1 or -1 throughout, a scalar bit on its own, or the longest run of open bits.
    """
    pieces: list[Piece] = []
    i = 0
    while i < len(bit_list):
        bit = bit_list[i]
        if bit is OPEN:
            j = i
            while j < len(bit_list) and bit_list[j] is OPEN:
                j += 1
            pieces.append(NoConnect(width=j - i))
            i = j
        elif bit.index is None:
            pieces.append(SignalRef(signal=bit.signal))
            i += 1
        else:
            run = [bit.index]
            step = 0
            j = i + 1
            while j < len(bit_list):
                nxt = bit_list[j]
                if nxt is OPEN or nxt.signal != bit.signal or nxt.index is None:
                    break
                delta = nxt.index - run[-1]
                if step == 0 and delta in (1, -1):
                    step = delta
                elif delta != step:
                    break
                run.append(nxt.index)
                j += 1
            pieces.append(_signal_ref(bit.signal, run, cell_nets[bit.signal]))
            i = j
    return tuple(pieces)


def _signal_ref(name: str, run: list[int], signal: Signal) -> SignalRef:
    r = Range(msb=run[0], lsb=run[-1])
    # A run that is exactly the whole bus, in its declared direction, is written without range.
    return SignalRef(signal=name) if r == signal.range else SignalRef(signal=name, range=r)


def canonicalize(netlist: Netlist) -> Netlist:
    """`netlist` with every connection in canonical form."""
    return dataclasses.replace(netlist, cells=tuple(_canonical_cell(cell) for cell in netlist.cells))


def _canonical_cell(cell: Cell) -> Cell:
    if not isinstance(cell, Subckt):
        return cell
    cell_nets = nets(cell)
    return dataclasses.replace(cell, instances=tuple(_canonical_instance(inst, cell_nets) for inst in cell.instances))


def _canonical_instance(inst: Instance, cell_nets: Mapping[str, Signal]) -> Instance:
    connections = tuple(
        dataclasses.replace(conn, pieces=canonical_pieces(bits(conn.pieces, cell_nets), cell_nets))
        for conn in inst.connections
    )
    return dataclasses.replace(inst, connections=connections)
