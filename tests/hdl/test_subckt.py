"""Subckts, external cells, two-call instances and connections."""

import pytest

import spicule.hdl as h
from spicule.dialects.cdl import syntax as cdl_syntax
from spicule.dialects.spectre import syntax as spectre_syntax
from spicule.hdl.builtins import cdl, spectre

NCH = h.External(
    "nch",
    element=h.MOS,
    ports=[h.Port(name="d"), h.Port(name="g"), h.Port(name="s"), h.Port(name="b")],
)


class Inv(h.Subckt):
    vdd = h.Port()
    vss = h.Port()
    a = h.Port()
    y = h.Port()
    nfin = h.Param(default=2)
    mn = NCH(nfin=nfin)(d=y, g=a, s=vss, b=vss)
    _helper = "kept out of the subckt"


def test_class_body_is_collected():
    info = h.info(Inv)
    assert info.name == "Inv"
    assert list(info.ports) == ["vdd", "vss", "a", "y"]
    assert list(info.params) == ["nfin"]
    assert list(info.instances) == ["mn"]
    assert Inv.vdd.name == "vdd" and Inv.vdd.owner is Inv


def test_the_class_name_is_the_cell_name():
    class inv_x4(h.Subckt):
        a = h.Port()

    assert h.info(inv_x4).name == "inv_x4"
    with pytest.raises(h.HdlError, match="not an identifier"):
        h.new_subckt("inv-x4")


def test_two_calls():
    call = Inv(nfin=4)
    assert isinstance(call, h.CellCall)
    a = h.Signal()
    b = h.Signal()
    vdd = h.Signal()
    vss = h.Signal()
    inst = call(vdd=vdd, vss=vss, a=a, y=b)
    assert isinstance(inst, h.Instance)
    assert set(inst._conns) == {"vdd", "vss", "a", "y"}
    assert inst._params["nfin"] is not None


def test_ports_in_the_first_call_or_parameters_in_the_second():
    vdd = h.Signal()
    with pytest.raises(h.HdlError, match="ports go in the second call"):
        Inv(vdd=vdd)
    with pytest.raises(h.HdlError, match="parameters go in the first call"):
        Inv()(nfin=2)


def test_subckt_parameters_are_closed():
    with pytest.raises(h.HdlError, match="has no parameter 'w'"):
        Inv(w=1)


def test_external_parameters_are_open():
    call = NCH(l=20e-9, nf=2, flavor="lvt")
    assert set(call.params) == {"l", "nf", "flavor"}
    assert call.params["flavor"] == "lvt"  # a str is a string parameter
    assert isinstance(call.params["l"], h.ParamExpr)  # anything else a number
    with pytest.raises(h.HdlError, match="not a number"):
        NCH(l=[1])


def test_connection_errors():
    d = h.Signal(width=4)
    a = h.Signal()
    with pytest.raises(h.HdlError, match="has no port 'q'"):
        Inv()(q=a)
    with pytest.raises(h.HdlError, match="1 bit"):
        Inv()(a=d)
    with pytest.raises(h.HdlError, match="can't be connected"):
        Inv()(a="a")
    inst = Inv()(a=a)
    with pytest.raises(h.HdlError, match="already connected"):
        inst.connect(a=a)


def test_stray_attributes_are_errors():
    with pytest.raises(h.HdlError, match="not a Port, Signal, Instance or Param"):

        class Stray(h.Subckt):
            x = 3

    with pytest.raises(h.HdlError, match="no connections"):

        class Forgot(h.Subckt):
            a = h.Port()
            i = Inv(nfin=2)


def test_subckts_cannot_be_subclassed():
    with pytest.raises(h.HdlError, match="can't be subclassed"):

        class Sub(Inv):
            pass


def test_new_subckt_and_assignment():
    m = h.new_subckt("buf")
    a = h.Port()
    y = h.Port()
    m.a = a
    m.y = y
    m.i0 = Inv()(a=a, y=y)
    info = h.info(m)
    assert info.name == "buf"
    assert list(info.ports) == ["a", "y"]
    assert list(info.instances) == ["i0"]
    assert a.owner is m and a.name == "a"
    with pytest.raises(h.HdlError, match="already has an attribute"):
        m.a = h.Port()
    with pytest.raises(h.HdlError):
        delattr(m, "a")


def test_net_belongs_to_one_subckt():
    a = h.Port()

    class One(h.Subckt):
        x = a

    with pytest.raises(h.HdlError, match="already belongs"):

        class Two(h.Subckt):
            y = a


@pytest.mark.parametrize(
    "make",
    [h.Signal, lambda: h.Param(default=1), lambda: spectre.resistor(r=1)(p=h.Signal(), n=h.Signal())],
    ids=["signal", "param", "instance"],
)
def test_one_object_has_one_name(make):
    with pytest.raises(h.HdlError, match="can't also be named 'b'"):

        class Twice(h.Subckt):
            a = make()
            b = a


def test_a_public_name_is_assigned_once():
    with pytest.raises(h.HdlError, match="'r0' is assigned twice"):

        class Twice(h.Subckt):
            a = h.Port()
            r0 = spectre.resistor(r=1)(p=a, n=a)
            r0 = spectre.resistor(r=2)(p=a, n=a)

    class Helpers(h.Subckt):  # helpers may change
        _x = 1
        _x = 2


def test_h_subckt_itself_is_no_cell():
    with pytest.raises(h.HdlError):
        h.Subckt()
    with pytest.raises(h.HdlError, match="not a subckt"):
        h.info(NCH)


def test_external_cell_declaration():
    cell = h.External("latch", element=h.SUBCKT, ports=[h.Port(name="clk"), h.Port(name="d", width=4)])
    model = cell.to_ir()
    assert [p.name for p in model.ports] == ["clk", "d"]
    assert model.ports[1].range is not None
    with pytest.raises(h.HdlError, match="duplicate port"):
        h.External("x", element=h.SUBCKT, ports=[h.Port(name="a"), h.Port(name="a")])
    with pytest.raises(h.HdlError, match="element"):
        h.External("x", element="mos", ports=[h.Port(name="a")])  # ty: ignore[invalid-argument-type]


def test_builtins_match_the_writers():
    assert set(spectre.BUILTINS) == spectre_syntax.BUILTINS
    assert set(cdl.BUILTINS) == set(cdl_syntax.BUILTINS)
    for cell in (*spectre.BUILTINS.values(), *cdl.BUILTINS.values()):
        assert cell.element is h.BUILTIN and cell.source is None
