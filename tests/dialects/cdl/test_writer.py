"""The CDL writer, against golden files in tests/dialects/cdl/golden/."""

import dataclasses
from pathlib import Path

import pytest

import spicule.ir as ir
from spicule.dialects import cdl
from spicule.dialects.cdl import syntax, writer
from spicule.dialects.common import WriterError

GOLDEN = Path(__file__).parent / "golden"


def sig(name: str, msb: int | None = None, lsb: int | None = None) -> ir.Signal:
    return ir.Signal(name=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb))


def s(name: str, msb: int | None = None, lsb: int | None = None) -> ir.SignalRef:
    return ir.SignalRef(
        signal=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb)
    )


def conn(port: str, *pieces: ir.Piece) -> ir.Connection:
    return ir.Connection(port=port, pieces=pieces)


def p(name: str, text: str) -> ir.ParamValue:
    return ir.ParamValue(name=name, value=ir.expr(text))


def decl(name: str, default: str | None = None) -> ir.ParamDecl:
    return ir.ParamDecl(name=name, type=ir.ParamType.NUMBER, default=None if default is None else ir.expr(default))


NCH = ir.External(
    name="nch", element=ir.Element.MOS, ports=(sig("d"), sig("g"), sig("s"), sig("b")), params=(decl("l"),)
)
PCH = dataclasses.replace(NCH, name="pch")
LATCH = ir.External(name="latch4", element=ir.Element.SUBCKT, ports=(sig("d", 3, 0), sig("q", 3, 0)))


def mos(name: str, cell: str, d: str, g: str, s_: str, *params: ir.ParamValue) -> ir.Instance:
    pins = (("d", d), ("g", g), ("s", s_), ("b", s_))
    return ir.Instance(name=name, cell=cell, connections=tuple(conn(port, s(net)) for port, net in pins), params=params)


INV = ir.Subckt(
    name="inv",
    ports=(sig("a"), sig("y"), sig("vdd"), sig("vss")),
    params=(decl("nfin", "2"),),
    instances=(
        mos("mn", "nch", "y", "a", "vss", p("l", "16e-9"), p("nfin", "nfin"), p("m", "1")),
        mos("p0", "pch", "y", "a", "vdd", p("l", "16e-9"), p("nfin", "pow(nfin, 2)/2")),
    ),
    meta=ir.Meta(origin="cells/inv.py:8"),
)

BANK = ir.Subckt(
    name="bank",
    ports=(sig("d", 3, 0), sig("q", 1, 0), sig("vdd"), sig("vss")),
    instances=(
        ir.Instance(
            name="u0", cell="latch4", connections=(conn("d", s("d")), conn("q", s("q"), ir.NoConnect(width=2)))
        ),
        ir.Instance(
            name="xi",
            cell="inv",
            connections=(
                conn("a", s("d", 0, 0)),
                conn("y", s("q", 0, 0)),
                conn("vdd", s("vdd")),
                conn("vss", s("vss")),
            ),
            params=(p("nfin", "4"),),
        ),
    ),
)

NETLIST = ir.Netlist(cells=(NCH, PCH, LATCH, INV, BANK))


def builtin(name: str) -> ir.External:
    """A built-in as the HDL will declare it: here just its two pins (external parameters are open)."""
    return ir.External(name=name, element=ir.Element.BUILTIN, ports=(sig("p"), sig("n")))


capacitor = builtin("capacitor")
resistor = builtin("resistor")


def golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if not path.exists():
        path.write_text(text)
        pytest.fail(f"wrote new golden file {path.name}: review it by hand, then run again")
    assert text == path.read_text()


def test_library():
    golden("library.cdl", cdl.write(NETLIST, origins=True))


def test_top_inlines_the_cell():
    text = cdl.write(NETLIST, top="bank")
    assert ".SUBCKT bank" not in text
    assert "Xxi d<0> q<0> vdd vss inv nfin=4" in text


def test_pow_is_written_with_the_real_exponent():
    # Calibre's pow() truncates its exponent; ** doesn't.
    assert "nfin='(nfin)**(2)/2'" in cdl.write(NETLIST)


def test_every_instance_gets_its_letter():
    text = cdl.write(NETLIST)
    assert "Mmn y a vss vss nch" in text
    assert "Mp0 y a vdd vdd pch" in text
    assert "Xu0 d<3> d<2> d<1> d<0> q<1> q<0> nc_u0_0 nc_u0_1 latch4" in text


def test_builtins_need_lvs_false():
    tb = ir.Subckt(
        name="rc",
        ports=(sig("a"), sig("b")),
        instances=(
            ir.Instance(
                name="r1", cell="resistor", connections=(conn("p", s("a")), conn("n", s("b"))), params=(p("r", "1e3"),)
            ),
            ir.Instance(
                name="c1",
                cell="capacitor",
                connections=(conn("p", s("b")), conn("n", s("a"))),
                params=(p("c", "10e-15"),),
            ),
        ),
    )
    netlist = ir.Netlist(cells=(resistor, capacitor, tb))
    with pytest.raises(WriterError, match="LVS netlist"):
        cdl.write(netlist)
    golden("builtins.cdl", cdl.write(netlist, lvs=False))


def test_required_subckt_parameters_are_refused():
    bare = dataclasses.replace(INV, params=(decl("nfin"),))
    netlist = dataclasses.replace(NETLIST, cells=tuple(bare if c.name == "inv" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="without a default"):
        cdl.write(netlist)


def test_case_only_clashes_are_refused():
    clash = dataclasses.replace(BANK, ports=(*BANK.ports, sig("VDD")))
    netlist = dataclasses.replace(NETLIST, cells=tuple(clash if c.name == "bank" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="case-insensitive"):
        cdl.write(netlist)


def test_write_is_the_package_function():
    assert cdl.write is writer.write
    assert syntax.BUS_FORMAT == "{name}<{index}>"
