"""Elaboration, against golden Spectre and CDL netlists in tests/hdl/golden/."""

import inspect
from pathlib import Path

import pytest

import spicule.hdl as h
import spicule.ir as ir
from spicule.dialects import cdl, spectre
from spicule.hdl.builtins import spectre as sp

GOLDEN = Path(__file__).parent / "golden"
HERE = "tests/hdl/test_elaborate.py"


def golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if not path.exists():
        path.write_text(text)
        pytest.fail(f"wrote new golden file {path.name}: review it by hand, then run again")
    assert text == path.read_text()


def line_of(obj: type) -> int:
    return inspect.getsourcelines(obj)[1]


# A small design, with lowercase cell names: PDK devices, a foreign subcircuit, subckts with buses and parameters, and a testbench.

nch = h.External(
    "nch", element=h.MOS, ports=[h.Port(name="d"), h.Port(name="g"), h.Port(name="s"), h.Port(name="b")]
)
pch = h.External(
    "pch", element=h.MOS, ports=[h.Port(name="d"), h.Port(name="g"), h.Port(name="s"), h.Port(name="b")]
)
latch = h.External("latch4", element=h.SUBCKT, ports=[h.Port(name="d", width=4), h.Port(name="q", width=4)])


class inv(h.Subckt):
    a = h.Port()
    y = h.Port()
    vdd = h.Port()
    vss = h.Port()
    nfin = h.Param(default=2)
    m = h.Param(default=1)
    mn = nch(nfin=nfin)(d=y, g=a, s=vss, b=vss)
    mp = pch(nfin=2 * nfin, l=h.fn.max(16e-9, nfin**2 * 4e-9))(d=y, g=a, s=vdd, b=vdd)


class bank(h.Subckt):
    d = h.Port(width=4)
    q = h.Port(msb=0, lsb=3)
    en = h.Port()
    vdd = h.Port()
    vss = h.Port()
    mid = h.Signal(width=4)
    u0 = latch()(d=h.Concat(d[3:2], en, h.NoConn(1)), q=mid)
    u1 = latch()(d=mid[0:3], q=q)
    x0 = inv(nfin=3, m=2)(a=en, y=h.NoConn(), vdd=vdd, vss=vss)


class Tb(h.Subckt):
    vdd = h.Signal()
    gnd = h.Signal()
    a = h.Signal()
    y = h.Signal()
    dut = inv(nfin=4)(a=a, y=y, vdd=vdd, vss=gnd)
    vs = sp.vsource(type="dc", dc=0.8)(p=vdd, n=gnd)
    va = sp.vsource(type="pulse", val0=0, val1=0.8, period=1e-9)(p=a, n=gnd)
    cl = sp.capacitor(c=1e-15)(p=y, n=gnd)


def test_spectre_testbench():
    golden("tb.scs", spectre.write(h.elaborate(Tb), top="Tb", ground="gnd"))


def test_cdl_library():
    golden("bank.cdl", cdl.write(h.elaborate(bank)))


def test_cells_leaves_first_each_once():
    netlist = h.elaborate(bank, Tb)
    names = [cell.name for cell in netlist.cells]
    assert names == ["latch4", "nch", "pch", "inv", "bank", "vsource", "capacitor", "Tb"]


def test_connections_are_canonical():
    cell = h.elaborate(bank).cells[-1]
    assert isinstance(cell, ir.Subckt)
    u0, u1 = cell.instances[0], cell.instances[1]
    assert u0.connections[0].pieces == (
        ir.SignalRef(signal="d", range=ir.Range(msb=3, lsb=2)),
        ir.SignalRef(signal="en"),
        ir.NoConnect(width=1),
    )
    assert u0.connections[1].pieces == (ir.SignalRef(signal="mid"),)
    assert u1.connections[0].pieces == (ir.SignalRef(signal="mid", range=ir.Range(msb=0, lsb=3)),)


def test_origins_relative_to_the_project():
    netlist = h.elaborate(Tb)
    by_name = {cell.name: cell for cell in netlist.cells}
    assert by_name["Tb"].meta.origin == f"{HERE}:{line_of(Tb)}"
    assert by_name["inv"].meta.origin == f"{HERE}:{line_of(inv)}"
    assert by_name["vsource"].meta.origin is None  # built-ins have no source line
    tb = by_name["Tb"]
    assert isinstance(tb, ir.Subckt)
    assert tb.instances[0].meta.origin == f"{HERE}:{line_of(Tb) + 5}"  # after the four signal lines


def test_origins_with_root():
    netlist = h.elaborate(Tb, root=Path(__file__).parents[3])
    assert netlist.cells[-1].meta.origin == f"spicule/{HERE}:{line_of(Tb)}"


def test_the_netlist_is_validated():
    netlist = h.elaborate(Tb)
    assert ir.check(netlist) == []


def test_needs_subckts():
    with pytest.raises(h.HdlError, match="at least one"):
        h.elaborate()
    with pytest.raises(h.HdlError, match="not a subckt"):
        h.elaborate(nch)


def test_same_name_twice_names_both_lines():
    def other():
        class inv(h.Subckt):
            a = h.Port()

        return inv

    Other = other()

    class Top(h.Subckt):
        a = h.Signal()
        y = h.Signal()
        vdd = h.Signal()
        vss = h.Signal()
        i0 = inv()(a=a, y=y, vdd=vdd, vss=vss)
        i1 = Other()(a=a)

    with pytest.raises(h.HdlError, match="both called 'inv'") as error:
        h.elaborate(Top)
    assert [s.line for s in error.value.sources] == [line_of(inv), line_of(Other)]


def test_unconnected_port():
    class Top(h.Subckt):
        a = h.Signal()
        i0 = inv()(a=a)

    with pytest.raises(h.HdlError, match="port 'y' of instance i0"):
        h.elaborate(Top)


def test_net_of_another_subckt():
    class Top(h.Subckt):
        a = h.Signal()
        i0 = pch()(d=a, g=inv.a, s=a, b=a)

    with pytest.raises(h.HdlError, match="belongs to subckt inv"):
        h.elaborate(Top)


def test_parameter_of_another_subckt():
    class Top(h.Subckt):
        a = h.Signal()
        i0 = pch(nfin=inv.nfin)(d=a, g=a, s=a, b=a)

    with pytest.raises(h.HdlError, match="may only use parameters of Top"):
        h.elaborate(Top)


def test_default_uses_a_later_parameter():
    later = h.Param(default=1)

    class Top(h.Subckt):
        a = h.Port()
        w = h.Param(default=2 * later)
        z = later

    with pytest.raises(h.HdlError, match="parameters declared before it"):
        h.elaborate(Top)


def test_cycle():
    m = h.new_subckt("loop")
    a = h.Port()
    m.a = a
    m.self = m()(a=a)
    with pytest.raises(h.HdlError, match="cycle: loop -> loop"):
        h.elaborate(m)


def test_rule_violations_point_at_the_instance():
    # The HDL checks values itself, so a wrong one is slipped in behind its back to reach the IR's A-3.
    class takes_w(h.Subckt):
        a = h.Port()
        w = h.Param(default=1)
        r0 = sp.resistor(r=w)(p=a, n=a)

    class Top(h.Subckt):
        a = h.Signal()
        i0 = takes_w(w=2)(a=a)

    Top.i0._params["w"] = "text"
    with pytest.raises(h.HdlError, match=r"\[A-3\]") as error:
        h.elaborate(Top)
    assert f"at tests/hdl/test_elaborate.py:{line_of(Top) + 2}" in str(error.value)  # relative, as meta.origin
    assert isinstance(error.value.__cause__, ir.ValidationError)


def test_lint_warns_with_lines():
    class Top(h.Subckt):
        a = h.Signal()
        b = h.Signal()
        i0 = sp.resistor(r=1)(p=a, n=a)

    with pytest.warns(h.HdlWarning, match=r"\[W-1\].*'b'"):
        h.elaborate(Top, lint=True)


def test_the_same_bit_twice_in_one_connection():
    two = h.External("two", element=h.SUBCKT, ports=[h.Port(name="x", width=2)])

    class Top(h.Subckt):
        d = h.Signal(width=4)
        u = two()(x=h.Concat(d[3], d[3]))
        v = two()(x=d[1:0])
        w = two()(x=d[3:2])

    assert "u (d\\<3\\> d\\<3\\>) two" in spectre.write(h.elaborate(Top))
