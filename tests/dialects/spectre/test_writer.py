"""The Spectre writer, against golden files in tests/dialects/spectre/golden/."""

import dataclasses
from pathlib import Path

import pytest

import spicule.ir as ir
from spicule import sim
from spicule.dialects import spectre
from spicule.dialects.common import WriterError
from spicule.dialects.spectre import syntax, writer

GOLDEN = Path(__file__).parent / "golden"


def sig(name: str, msb: int | None = None, lsb: int | None = None) -> ir.Signal:
    return ir.Signal(name=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb))


def conn(port: str, *pieces: ir.Piece) -> ir.Connection:
    return ir.Connection(port=port, pieces=pieces)


def s(name: str, msb: int | None = None, lsb: int | None = None) -> ir.SignalRef:
    return ir.SignalRef(
        signal=name, range=None if msb is None else ir.Range(msb=msb, lsb=lsb if lsb is not None else msb)
    )


def p(name: str, text: str) -> ir.ParamValue:
    return ir.ParamValue(name=name, value=ir.expr(text))


def decl(name: str, default: str) -> ir.ParamDecl:
    return ir.ParamDecl(name=name, default=ir.expr(default))


NCH = ir.External(
    name="nch",
    element=ir.Element.MOS,
    ports=(sig("d"), sig("g"), sig("s"), sig("b")),
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


def builtin(name: str) -> ir.External:
    """A built-in as the HDL will declare it: here just its two pins (external parameters are open)."""
    return ir.External(name=name, element=ir.Element.BUILTIN, ports=(sig("p"), sig("n")))


resistor = builtin("resistor")
vsource = builtin("vsource")


def golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if not path.exists():
        path.write_text(text)
        pytest.fail(f"wrote new golden file {path.name}: review it by hand, then run again")
    assert text == path.read_text()


def test_library():
    golden("library.scs", spectre.write(NETLIST))


def test_testbench_with_ground_and_origins():
    golden("tb.scs", spectre.write(sim.Simulation(NETLIST, top="tb", ground="gnd"), origins=True))


def test_bus_format_option():
    text = spectre.write(sim.Simulation(NETLIST, top="tb", ground="gnd"), bus_format="{name}[{index}]")
    assert "b0 (d[0] d[1] d[2] d[3] q[1] q[0]) bank" in text


def test_bus_format_must_keep_names_unique():
    clash = dataclasses.replace(TB, signals=(*TB.signals, sig("d_3")))
    netlist = dataclasses.replace(NETLIST, cells=(*NETLIST.cells[:-1], clash))
    with pytest.raises(WriterError, match="both spelled"):
        spectre.write(sim.Simulation(netlist, top="tb", ground="gnd"), bus_format="{name}_{index}")


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
    assert syntax.BUS_FORMAT == r"{name}\<{index}\>"


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
    text = spectre.write(sim.Simulation(ir.Netlist(cells=(vsource, resistor, tb)), top="tb_rc", ground="gnd"))
    golden("builtins.scs", text)


def test_unknown_builtin():
    fake = ir.External(name="vmagic", element=ir.Element.BUILTIN, ports=(sig("p"), sig("n")))
    tb = ir.Subckt(
        name="tb",
        signals=(sig("a"),),
        instances=(ir.Instance(name="x", cell="vmagic", connections=(conn("p", s("a")), conn("n", s("a")))),),
    )
    with pytest.raises(WriterError, match="not a Spectre built-in"):
        spectre.write(ir.Netlist(cells=(fake, tb)))


def test_reserved_parameter_names_on_subcircuits():
    hot = dataclasses.replace(INV, params=(*INV.params, decl("temp", "27")))
    netlist = dataclasses.replace(NETLIST, cells=tuple(hot if c.name == "inv" else c for c in NETLIST.cells))
    with pytest.raises(WriterError, match="reserved"):
        spectre.write(netlist)


def deck_netlist() -> ir.Netlist:
    res = builtin("resistor")
    top = ir.Subckt(
        name="tb",
        signals=(sig("a"), sig("gnd")),
        params=(decl("w", "2"), decl("x", "2*w")),
        instances=(
            ir.Instance(
                name="r0",
                cell="resistor",
                connections=(conn("p", s("a")), conn("n", s("gnd"))),
                params=(p("r", "x"),),
            ),
        ),
    )
    return ir.Netlist(cells=(res, top))


def test_parameters_of_the_top_cell_are_written():
    text = spectre.write(sim.Simulation(deck_netlist(), top="tb", ground="gnd"))
    assert "simulator lang=spectre\n\nparameters w=2 x=2*w\n\n// top: tb\nr0 (a 0) resistor r=x\n" in text


def test_params_override_the_defaults_in_place():
    run = sim.Simulation(deck_netlist(), top="tb", ground="gnd", params={"w": 0.7})
    assert "parameters w=700e-3 x=2*w\n" in spectre.write(run)


def test_a_library_has_no_top_level():
    text = spectre.write(deck_netlist())
    assert "subckt tb (" in text and "parameters w=2 x=2*w\n    r0 (a gnd) resistor r=x\nends tb\n" in text


def test_the_deck():
    run = sim.Simulation(
        deck_netlist(),
        top="tb",
        ground="gnd",
        params={"w": 0.7},
        includes=[sim.Include("models.scs", section="tt"), sim.Include("more models.scs")],
        options=sim.Options("opts", temp=27, reltol=1e-4),
        saves=["a", "r0:1"],
        raw=["ic a=0", "statistics {\n    process {\n    }\n}"],
        analyses=[
            sim.Analysis("op", "dc"),
            sim.Analysis("tr", "tran", stop=1e-9, errpreset="conservative"),
            sim.Raw("// between the analyses"),
            sim.Analysis(
                "sw",
                "sweep",
                param="w",
                values=[0.6, -0.8, ir.expr("w"), ir.expr("-w"), ir.expr("1 + w"), ir.expr("-(1 + w)")],
                children=[sim.Analysis("tr", "tran", stop=1e-9), sim.Raw("// in the sweep")],
            ),
            sim.Analysis("mc", "montecarlo", numruns=100, variations="mismatch", children=[sim.Analysis("op", "dc")]),
        ],
    )
    golden("deck.scs", spectre.write(run))


def test_analysis_types_are_spectres():
    run = sim.Simulation(deck_netlist(), top="tb", ground="gnd", analyses=[sim.Analysis("tr", "trann", stop=1)])
    with pytest.raises(WriterError, match="'trann' is not a Spectre analysis"):
        spectre.write(run)


def test_only_some_analyses_have_children():
    child = sim.Analysis("op", "dc")
    run = sim.Simulation(deck_netlist(), top="tb", ground="gnd", analyses=[sim.Analysis("t", "tran", children=[child])])
    with pytest.raises(WriterError, match="a tran has no child analyses"):
        spectre.write(run)


def test_a_child_is_checked_too():
    child = sim.Analysis("save", "dc")
    run = sim.Simulation(
        deck_netlist(), top="tb", ground="gnd", analyses=[sim.Analysis("s", "sweep", children=[child])]
    )
    with pytest.raises(WriterError, match="'save' is a Spectre keyword"):
        spectre.write(run)


def test_options_name_is_checked():
    run = sim.Simulation(deck_netlist(), top="tb", ground="gnd", options=sim.Options("save", temp=27))
    with pytest.raises(WriterError, match="'save' is a Spectre keyword"):
        spectre.write(run)
