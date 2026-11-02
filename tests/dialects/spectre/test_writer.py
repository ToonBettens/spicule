"""The Spectre writer, against golden files in tests/dialects/spectre/golden/."""

import dataclasses
from pathlib import Path

import pytest

import spicule.ir as ir
from spicule.dialects import spectre
from spicule.dialects.common import WriterError
from spicule.dialects.spectre import writer
from spicule.dialects.spectre.builtins import resistor, vsource

GOLDEN = Path(__file__).parent / "golden"


def sig(name: str, msb: int | None = None, lsb: int | None = None) -> ir.Signal:
    return ir.Signal(name=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb))


def conn(port: str, *pieces: ir.Piece) -> ir.Connection:
    return ir.Connection(port=port, pieces=pieces)


def s(name: str, msb: int | None = None, lsb: int | None = None) -> ir.Slice:
    return ir.Slice(signal=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb))


def p(name: str, text: str) -> ir.ParamValue:
    return ir.ParamValue(name=name, value=ir.expr(text))


NUM = ir.ParamType.NUMBER


def decl(name: str, default: str | None = None) -> ir.ParamDecl:
    return ir.ParamDecl(name=name, type=NUM, default=None if default is None else ir.expr(default))


NCH = ir.External(
    name="nch",
    element=ir.Element.MOS,
    ports=(sig("d"), sig("g"), sig("s"), sig("b")),
    params=(decl("l", "16e-9"), decl("nfin", "2"), decl("nf", "1"), decl("m", "1")),
)
PCH = dataclasses.replace(NCH, name="pch")
LATCH = ir.External(name="latch4", element=ir.Element.SUBCKT, ports=(sig("d", 3, 0), sig("q", 3, 0)))


def mos(name: str, cell: str, d: str, g: str, s_: str, b: str, *params: ir.ParamValue) -> ir.Instance:
    pins = (("d", d), ("g", g), ("s", s_), ("b", b))
    return ir.Instance(name=name, cell=cell, connections=tuple(conn(port, s(net)) for port, net in pins), params=params)


INV = ir.Subckt(
    name="inv",
    ports=(sig("a"), sig("y"), sig("vdd"), sig("vss")),
    params=(decl("nfin", "2"), decl("m", "1")),
    instances=(
        mos("mn", "nch", "y", "a", "vss", "vss", p("nfin", "nfin")),
        mos("mp", "pch", "y", "a", "vdd", "vdd", p("nfin", "2*nfin"), p("l", "max(16e-9, pow(2, 3)*2e-9)")),
    ),
    meta=ir.Meta(origin="cells/inv.py:8"),
)

BUF = ir.Subckt(
    name="buf",
    ports=(sig("a"), sig("y"), sig("vdd"), sig("vss")),
    signals=(sig("mid"),),
    instances=(
        ir.Instance(
            name="i0",
            cell="inv",
            connections=(conn("a", s("a")), conn("y", s("mid")), conn("vdd", s("vdd")), conn("vss", s("vss"))),
        ),
        ir.Instance(
            name="i1",
            cell="inv",
            connections=(conn("a", s("mid")), conn("y", s("y")), conn("vdd", s("vdd")), conn("vss", s("vss"))),
            params=(p("m", "2"),),
            meta=ir.Meta(origin="cells/buf.py:14"),
        ),
    ),
)

BANK = ir.Subckt(
    name="bank",
    ports=(sig("d", 3, 0), sig("q", 1, 0)),
    instances=(
        ir.Instance(
            name="u0", cell="latch4", connections=(conn("d", s("d")), conn("q", s("q"), ir.NoConnect(width=2)))
        ),
    ),
)

TB = ir.Subckt(
    name="tb",
    signals=(sig("in"), sig("out"), sig("vdd"), sig("gnd"), sig("d", 3, 0), sig("q", 1, 0)),
    instances=(
        ir.Instance(
            name="dut",
            cell="buf",
            connections=(conn("a", s("in")), conn("y", s("out")), conn("vdd", s("vdd")), conn("vss", s("gnd"))),
        ),
        ir.Instance(name="b0", cell="bank", connections=(conn("d", s("d", 0, 3)), conn("q", s("q")))),
    ),
)

NETLIST = ir.Netlist(cells=(NCH, PCH, LATCH, INV, BUF, BANK, TB))


def golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if not path.exists():
        path.write_text(text)
        pytest.fail(f"wrote new golden file {path.name}: review it by hand, then run again")
    assert text == path.read_text()


def test_library():
    golden("library.scs", spectre.write(NETLIST))


def test_testbench_with_ground_and_origins():
    golden("tb.scs", spectre.write(NETLIST, top="tb", ground="gnd", origins=True))


def test_bus_format_option():
    text = spectre.write(NETLIST, top="tb", bus_format="{name}[{index}]")
    assert "b0 (d[0] d[1] d[2] d[3] q[1] q[0]) bank" in text


def test_bus_format_must_keep_names_unique():
    clash = dataclasses.replace(TB, signals=(*TB.signals, sig("d_3")))
    netlist = dataclasses.replace(NETLIST, cells=(*NETLIST.cells[:-1], clash))
    with pytest.raises(WriterError, match="both spelled"):
        spectre.write(netlist, top="tb", bus_format="{name}_{index}")


def test_ground_must_be_a_scalar_net_of_the_top():
    with pytest.raises(WriterError, match="ground"):
        spectre.write(NETLIST, top="tb", ground="d")
    with pytest.raises(WriterError, match="needs a top"):
        spectre.write(NETLIST, ground="gnd")


def test_m_default_must_be_one():
    odd = dataclasses.replace(INV, params=(decl("nfin", "2"), decl("m", "2")))
    netlist = dataclasses.replace(NETLIST, cells=tuple(odd if c.name == "inv" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="defaults to 1"):
        spectre.write(netlist)


def test_m_not_used_inside():
    inner = dataclasses.replace(
        INV, instances=(mos("mn", "nch", "y", "a", "vss", "vss", p("m", "2*m")), INV.instances[1])
    )
    netlist = dataclasses.replace(NETLIST, cells=tuple(inner if c.name == "inv" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="m in expressions"):
        spectre.write(netlist)


def test_keywords_are_rejected():
    bad = dataclasses.replace(BANK, instances=(dataclasses.replace(BANK.instances[0], name="model"),))
    netlist = dataclasses.replace(NETLIST, cells=tuple(bad if c.name == "bank" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="keyword"):
        spectre.write(netlist)


def test_write_is_the_package_function():
    assert spectre.write is writer.write
    assert writer.BUS_FORMAT == r"{name}\<{index}\>"


def test_invalid_netlists_are_refused():
    with pytest.raises(ir.ValidationError):
        spectre.write(ir.Netlist())


def test_builtins():
    tb = ir.Subckt(
        name="tb_rc",
        signals=(sig("vin"), sig("gnd")),
        instances=(
            ir.Instance(
                name="v0",
                cell="vsource",
                connections=(conn("p", s("vin")), conn("n", s("gnd"))),
                params=(ir.ParamValue(name="type", value="dc"), p("dc", "0.8")),
            ),
            ir.Instance(
                name="r0",
                cell="resistor",
                connections=(conn("p", s("vin")), conn("n", s("gnd"))),
                params=(p("r", "1e3"), ir.ParamValue(name="isnoisy", value="no")),
            ),
        ),
    )
    text = spectre.write(ir.Netlist(cells=(vsource, resistor, tb)), top="tb_rc", ground="gnd")
    golden("builtins.scs", text)


def test_unknown_builtin():
    fake = ir.External(name="vmagic", element=ir.Element.BUILTIN, ports=(sig("p"), sig("n")))
    tb = ir.Subckt(
        name="tb",
        signals=(sig("a"),),
        instances=(ir.Instance(name="x", cell="vmagic", connections=(conn("p", s("a")), conn("n", s("a")))),),
    )
    with pytest.raises(WriterError, match="not a Spectre built-in"):
        spectre.write(ir.Netlist(cells=(fake, tb)), top="tb")


def test_reserved_parameter_names_on_subcircuits():
    hot = dataclasses.replace(INV, params=(*INV.params, decl("temp", "27")))
    netlist = dataclasses.replace(NETLIST, cells=tuple(hot if c.name == "inv" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="reserved"):
        spectre.write(netlist)
