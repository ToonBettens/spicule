"""Bits, canonical pieces and canonicalize() (spec 6.3), and the connection rules C-1 to C-5 and warnings W-1 to
W-3 of the validator."""

import dataclasses

import pytest

import spicule.ir as ir
from spicule.ir.connections import OPEN, NetBit, bits, canonical_pieces, indices

D = ir.Signal(name="d", range=ir.Range(msb=7, lsb=0))
EN = ir.Signal(name="en")
NETS = {"d": D, "en": EN}


def s(name: str, msb: int | None = None, lsb: int | None = None) -> ir.SignalRef:
    if msb is None:
        return ir.SignalRef(signal=name)
    return ir.SignalRef(signal=name, range=ir.Range(msb=msb, lsb=lsb if lsb is not None else msb))


def test_indices_follow_the_range_direction():
    assert indices(ir.Range(msb=3, lsb=0)) == [3, 2, 1, 0]
    assert indices(ir.Range(msb=0, lsb=3)) == [0, 1, 2, 3]
    assert indices(ir.Range(msb=5, lsb=5)) == [5]


def test_bits_expand_whole_signals_and_open_bits():
    assert bits((s("en"), ir.NoConnect(width=2), s("d", 1, 0)), NETS) == [
        NetBit("en", None),
        OPEN,
        OPEN,
        NetBit("d", 1),
        NetBit("d", 0),
    ]
    assert len(bits((s("d"),), NETS)) == 8


@pytest.mark.parametrize(
    ("pieces", "canonical"),
    [
        pytest.param((s("d", 7, 0),), (s("d"),), id="whole-bus-in-declared-direction"),
        pytest.param((s("d", 0, 7),), (s("d", 0, 7),), id="whole-bus-reversed-keeps-range"),
        pytest.param((s("d", 3, 2), s("d", 1, 0)), (s("d", 3, 0),), id="adjacent-runs-merge"),
        pytest.param((s("d", 3, 2), s("d", 5, 6)), (s("d", 3, 2), s("d", 5, 6)), id="spec-example"),
        pytest.param((s("d", 3), s("d", 4)), (s("d", 3, 4),), id="single-bits-form-a-run"),
        pytest.param((s("d", 2), s("d", 4)), (s("d", 2), s("d", 4)), id="gap-breaks-a-run"),
        pytest.param((s("en"), s("en")), (s("en"), s("en")), id="scalars-stay-single"),
        pytest.param((ir.NoConnect(width=1), ir.NoConnect(width=2)), (ir.NoConnect(width=3),), id="open-bits-merge"),
    ],
)
def test_canonical_pieces(pieces, canonical):
    assert canonical_pieces(bits(pieces, NETS), NETS) == canonical


def test_canonicalize_rewrites_every_connection():
    tb = ir.Subckt(
        name="tb",
        signals=(D,),
        instances=(
            ir.Instance(
                name="u", cell="blk", connections=(ir.Connection(port="i", pieces=(s("d", 7, 4), s("d", 3, 0))),)
            ),
        ),
    )
    blk = ir.External(name="blk", element=ir.Element.SUBCKT, ports=(ir.Signal(name="i", range=ir.Range(msb=7, lsb=0)),))
    netlist = ir.Netlist(cells=(blk, tb))
    fixed = ir.canonicalize(netlist)
    assert fixed.cells[1].instances[0].connections[0].pieces == (s("d"),)  # ty: ignore[unresolved-attribute]
    assert ir.check(fixed) == []
    assert {v.rule for v in ir.check(netlist)} == {"C-5"}


# The connection rules on a small netlist: a 4-bit buffer `buf` used once in `tb`.

BUF = ir.External(
    name="buf",
    element=ir.Element.SUBCKT,
    ports=(ir.Signal(name="i", range=ir.Range(msb=3, lsb=0)), ir.Signal(name="o", range=ir.Range(msb=3, lsb=0))),
)


def tb_with(*connections: ir.Connection) -> ir.Netlist:
    tb = ir.Subckt(
        name="tb",
        signals=(
            ir.Signal(name="a", range=ir.Range(msb=3, lsb=0)),
            ir.Signal(name="y", range=ir.Range(msb=3, lsb=0)),
            EN,
        ),
        instances=(ir.Instance(name="u", cell="buf", connections=connections),),
    )
    return ir.Netlist(cells=(BUF, tb))


IN = ir.Connection(port="i", pieces=(s("a"),))
OUT = ir.Connection(port="o", pieces=(s("y"),))


def rules(netlist: ir.Netlist) -> set[str]:
    return {v.rule for v in ir.check(netlist)}


def test_connected_buffer_is_valid():
    assert ir.check(tb_with(IN, OUT)) == []


def test_c1_every_port_exactly_once():
    assert rules(tb_with(IN)) == {"C-1"}  # o missing
    assert rules(tb_with(IN, OUT, OUT)) == {"C-1"}  # o twice
    assert rules(tb_with(IN, OUT, ir.Connection(port="x", pieces=(s("en"),)))) == {"C-1"}  # no port x


def test_c2_signal_refs_name_signals_of_the_cell():
    assert rules(tb_with(IN, ir.Connection(port="o", pieces=(s("missing"),)))) == {"C-2"}


def test_c3_ranges_only_on_buses_and_within():
    assert rules(tb_with(IN, ir.Connection(port="o", pieces=(s("en", 0), s("y", 2, 0))))) == {"C-3"}
    assert rules(tb_with(IN, ir.Connection(port="o", pieces=(s("y", 4, 1),)))) == {"C-3"}


def test_c4_widths_add_up():
    assert rules(tb_with(IN, ir.Connection(port="o", pieces=(s("y", 2, 0),)))) == {"C-4"}
    assert rules(tb_with(IN, ir.Connection(port="o", pieces=(s("y", 2, 0), ir.NoConnect(width=1))))) == set()


def test_c5_canonical_form():
    [v] = ir.check(tb_with(IN, ir.Connection(port="o", pieces=(s("y", 3, 2), s("y", 1, 0)))))
    assert v.rule == "C-5"
    assert v.message.endswith("write y")
    assert (v.cell, v.instance) == ("tb", "u")


def test_connections_of_broken_references_are_not_checked():
    netlist = tb_with(IN)  # o missing, but the instance also refers to a missing cell
    netlist = dataclasses.replace(netlist, cells=netlist.cells[1:])
    assert rules(netlist) == {"D-1"}


# Warnings


def warnings(netlist: ir.Netlist) -> list[tuple[str, str]]:
    return [(v.rule, v.message) for v in ir.lint(netlist)]


def test_lint_reports_floating_nets():
    pair = ir.Subckt(
        name="pair",
        ports=(ir.Signal(name="i", range=ir.Range(msb=1, lsb=0)), ir.Signal(name="o")),
        signals=(ir.Signal(name="spare"), ir.Signal(name="half", range=ir.Range(msb=1, lsb=0))),
        instances=(
            ir.Instance(
                name="u",
                cell="cap",
                connections=(
                    ir.Connection(port="p", pieces=(s("i", 1),)),
                    ir.Connection(port="n", pieces=(s("half", 0),)),
                ),
            ),
        ),
    )
    cap = ir.External(name="cap", element=ir.Element.CAPACITOR, ports=(ir.Signal(name="p"), ir.Signal(name="n")))
    netlist = ir.Netlist(cells=(cap, pair))
    assert ir.check(netlist) == []
    assert warnings(netlist) == [
        ("W-2", "port bit i<0> is not used inside the cell"),
        ("W-2", "port bit o is not used inside the cell"),
        ("W-1", "signal 'spare' is not connected to anything"),
        ("W-3", "net bit half<1> is connected 0 time(s), so it floats"),
        ("W-3", "net bit half<0> is connected 1 time(s), so it floats"),
    ]


def test_open_bits_dont_count_as_connections():
    # Port o is left open, so nothing reaches signal y: it is unused, not "connected four times".
    found = warnings(tb_with(IN, ir.Connection(port="o", pieces=(ir.NoConnect(width=4),))))
    assert ("W-1", "signal 'y' is not connected to anything") in found


def test_a_repeated_bit_starts_a_new_piece():
    declared = {"d": ir.Signal(name="d", range=ir.Range(msb=3, lsb=0))}
    bit = ir.connections.NetBit
    assert ir.connections.canonical_pieces([bit("d", 3), bit("d", 3)], declared) == (s("d", 3), s("d", 3))
    assert ir.connections.canonical_pieces([bit("d", 3), bit("d", 2), bit("d", 2)], declared) == (
        s("d", 3, 2),
        s("d", 2),
    )
