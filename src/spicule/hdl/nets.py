"""Ports, signals, slices, concatenations and open pins.

A bus has real bit indices, msb on the left, in either direction. Indexing uses those
indices, inclusive on both ends and in the order written. It is not a Python list slice::

    d = h.Port(msb=7, lsb=4)    # d<7:4>
    d[5]                        # d<5>
    d[7:6]                      # d<7:6>, two bits
    d[4:7]                      # d<4:7>, four bits, reversed
    d[7:]  d[-1]  d[7:4:2]      # errors: no open ends, negative indices or steps
    *d                          # d<7>, d<6>, d<5>, d<4>: a bus unpacks into its bits
    h.Concat(a, d[5:4])         # a's bits, then d<5>, d<4>. In a connection also (a, d[5:4])
    h.NoConn()                  # bits left open on purpose
    a, y = h.Ports(2)           # several nets at once
"""

from collections.abc import Iterator

from spicule import ir
from spicule.hdl.source import HdlError, Source, caller, check_identifier


class Connectable:
    """Anything an instance port can be connected to."""

    source: Source | None

    @property
    def width(self) -> int | None:
        """Width in bits. None for a `NoConn` that takes its width from the port."""
        raise NotImplementedError

    def nets(self) -> tuple[Net, ...]:
        """The nets it connects to."""
        return ()

    def to_ir(self, port_width: int) -> tuple[ir.Piece, ...]:
        """This connection as IR pieces, on a port of `port_width` bits."""
        raise NotImplementedError

    def __iter__(self) -> Iterator[Slice]:
        raise HdlError(f"{self!r} can't be iterated; only a bus unpacks into its bits", caller())


def _check_index(i: object, what: str, source: Source | None) -> int:
    if isinstance(i, bool) or not isinstance(i, int) or i < 0:
        raise HdlError(f"{what}: bus indices must be ints >= 0, got {i!r}", source)
    return i


def _check_width(width: object, what: str, source: Source | None) -> None:
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise HdlError(f"{what}: width must be an int >= 1, got {width!r}", source)


def _msb_lsb(what: str, key: object, source: Source | None) -> tuple[int, int]:
    """The `(msb, lsb)` of an index or a `[msb:lsb]` slice. The indices themselves are checked by `_check_bits`."""
    if isinstance(key, bool) or not isinstance(key, int | slice):
        raise HdlError(f"{what} is indexed with {key!r}; use an int or [msb:lsb]", source)
    if isinstance(key, int):
        return key, key
    if key.step is not None:
        raise HdlError(f"{what}[{key.start}:{key.stop}:{key.step}]: steps are not supported", source)
    if key.start is None or key.stop is None:
        raise HdlError(f"{what}: slices need both ends, [msb:lsb] (inclusive)", source)
    return key.start, key.stop


def _check_bits(what: str, within: ir.Range, msb: int, lsb: int, source: Source | None) -> ir.Range:
    """`<msb:lsb>` as a range, if both ends are bits of the range `within`."""
    bits = ir.connections.indices(within)
    for i in (msb, lsb):
        _check_index(i, what, source)
        if i not in bits:
            raise HdlError(f"{what}[{i}]: index outside {min(bits)}..{max(bits)}", source)
    return ir.Range(msb=msb, lsb=lsb)


class Net(Connectable):
    """A scalar or bus net of a subckt."""

    def __init__(
        self, *, width: int | None = None, msb: int | None = None, lsb: int | None = None, name: str | None = None
    ):
        self.source = caller()
        if width is not None:
            if msb is not None or lsb is not None:
                raise HdlError(f"{self.kind}: give either width= or msb= and lsb=, not both", self.source)
            _check_width(width, self.kind, self.source)
            msb, lsb = width - 1, 0
        elif (msb is None) != (lsb is None):
            raise HdlError(f"{self.kind}: a bus needs both msb= and lsb=", self.source)
        self.range: ir.Range | None = None
        if msb is not None and lsb is not None:
            _check_index(msb, self.kind, self.source)
            _check_index(lsb, self.kind, self.source)
            self.range = ir.Range(msb=msb, lsb=lsb)
        self.name: str | None = None
        self.owner: object | None = None  # The subckt (class) or external cell it belongs to
        if name is not None:
            self.name = check_identifier(name, f"{self.kind} name", self.source)

    def __set_name__(self, owner: object, name: str) -> None:
        # Called for class bodies, and by the subckt metaclass for attributes assigned later.
        if self.owner is not None and self.owner is not owner:
            raise HdlError(f"{self} already belongs to {self.owner}; create a new one", self.source)
        if self.owner is not None and self.name != name:
            raise HdlError(f"{self.kind} {self.name!r} can't also be named {name!r}; create a new one", self.source)
        if self.name is not None and self.name != name:
            raise HdlError(f"{self} was created with name {self.name!r} but assigned to {name!r}", self.source)
        self.name = check_identifier(name, f"{self.kind} name", self.source)
        self.owner = owner

    @property
    def kind(self) -> str:
        """What error messages call it: `port` or `signal`."""
        return type(self).__name__.lower()

    @property
    def width(self) -> int:
        return ir.connections.width(self.range)

    def nets(self) -> tuple[Net, ...]:
        return (self,)

    def to_decl(self) -> ir.Signal:
        assert self.name is not None
        return ir.Signal(name=self.name, range=self.range)

    def to_ir(self, port_width: int) -> tuple[ir.Piece, ...]:
        assert self.name is not None
        return (ir.SignalRef(signal=self.name),)

    def __getitem__(self, key: int | slice) -> Slice:
        return Slice(self, *_msb_lsb(str(self), key, caller()))

    def __iter__(self) -> Iterator[Slice]:
        if self.range is None:
            return super().__iter__()
        return iter([Slice(self, i, i) for i in ir.connections.indices(self.range)])

    def __repr__(self) -> str:
        bus = "" if self.range is None else f"<{self.range.msb}:{self.range.lsb}>"
        return f"{type(self).__name__}({self.name or '?'}{bus})"

    def __str__(self) -> str:
        return f"{self.kind} {self.name or '?'}"


class Port(Net):
    """A port of a subckt: `h.Port()` (scalar), `h.Port(width=8)` (<7:0>), `h.Port(msb=0, lsb=3)` (<0:3>)."""


class Signal(Net):
    """An internal net of a subckt, declared like a `Port`."""


def Ports(count: int, *, width: int | None = None, msb: int | None = None, lsb: int | None = None) -> tuple[Port, ...]:
    """`count` new ports, all of one shape: `a, y = h.Ports(2)`, `d, q = h.Ports(2, width=4)`."""
    return tuple(Port(width=width, msb=msb, lsb=lsb) for _ in range(_check_count(count)))


def Signals(
    count: int, *, width: int | None = None, msb: int | None = None, lsb: int | None = None
) -> tuple[Signal, ...]:
    """`count` new signals, all of one shape: `a, y = h.Signals(2)`, `d, q = h.Signals(2, width=4)`."""
    return tuple(Signal(width=width, msb=msb, lsb=lsb) for _ in range(_check_count(count)))


def _check_count(count: object) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise HdlError(f"the number of nets must be an int >= 1, got {count!r}", caller())
    return count


class NoConn(Connectable):
    """Bits deliberately left open. The width comes from the port, unless given (needed inside a `Concat`)."""

    def __init__(self, width: int | None = None):
        self.source = caller()
        if width is not None:
            _check_width(width, "NoConn", self.source)
        self._width = width

    @property
    def width(self) -> int | None:
        return self._width

    def to_ir(self, port_width: int) -> tuple[ir.Piece, ...]:
        return (ir.NoConnect(width=self._width or port_width),)

    def __repr__(self) -> str:
        return f"NoConn({self._width or ''})"


class Slice(Connectable):
    """Bits `<msb:lsb>` of a bus port or signal, in the order written. `d[7:4]` is short for `h.Slice(d, 7, 4)`."""

    def __init__(self, net: Net, msb: int, lsb: int):
        self.source = caller()
        if net.range is None:
            raise HdlError(f"{net} is a scalar and can't be indexed", self.source)
        self.range = _check_bits(str(net), net.range, msb, lsb, self.source)
        self.net = net

    @property
    def width(self) -> int:
        return ir.connections.width(self.range)

    def nets(self) -> tuple[Net, ...]:
        return (self.net,)

    def __getitem__(self, key: int | slice) -> Slice:
        source = caller()
        inner = _check_bits(repr(self), self.range, *_msb_lsb(repr(self), key, source), source)
        return Slice(self.net, inner.msb, inner.lsb)

    def __iter__(self) -> Iterator[Slice]:
        return iter([Slice(self.net, i, i) for i in ir.connections.indices(self.range)])

    def to_ir(self, port_width: int) -> tuple[ir.Piece, ...]:
        assert self.net.name is not None
        return (ir.SignalRef(signal=self.net.name, range=self.range),)

    def __repr__(self) -> str:
        return f"{self.net.name or '?'}<{self.range.msb}:{self.range.lsb}>"


class Concat(Connectable):
    """
    Parts in expansion order, as written: `h.Concat(a, b[3:2], h.NoConn(2))`. A tuple is a concatenation too, in a
    connection or as a part: `x=(a, b[3:2], h.NoConn(2))`.
    """

    def __init__(self, *parts: Connectable | tuple):
        self.source = caller()
        flat: list[Connectable] = []
        total = 0
        for part in parts:
            if isinstance(part, tuple):
                part = Concat(*part)
            if not isinstance(part, Connectable):
                raise HdlError(f"Concat part {part!r} is not connectable", self.source)
            width = part.width
            if width is None:
                raise HdlError(f"{part!r} inside a Concat needs an explicit width", self.source)
            flat.extend(part.parts if isinstance(part, Concat) else [part])
            total += width
        if not flat:
            raise HdlError("empty Concat", self.source)
        self.parts = flat
        self._width = total

    @property
    def width(self) -> int:
        return self._width

    def nets(self) -> tuple[Net, ...]:
        return tuple(net for part in self.parts for net in part.nets())

    def to_ir(self, port_width: int) -> tuple[ir.Piece, ...]:
        return tuple(piece for part in self.parts for piece in part.to_ir(port_width))

    def __repr__(self) -> str:
        return f"Concat({', '.join(map(repr, self.parts))})"
