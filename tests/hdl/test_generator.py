"""Generators: families of cells, named by a format on the decorator."""

from dataclasses import dataclass

import pytest

import spicule.hdl as h
import spicule.ir as ir
from spicule.dialects import spectre
from spicule.hdl.builtins import spectre as sp


@dataclass(frozen=True)
class Size:
    nf: int


@h.generator("chain_n{n}")
def chain(*, n: int = 2) -> type[h.Subckt]:
    class chain(h.Subckt):
        a, y, gnd = h.Ports(3)
        r = h.Param(1e3)
        mid = h.Signal(width=n + 1)
        first = sp.resistor(r=r)(p=a, n=mid[0])
        last = sp.resistor(r=r)(p=mid[n], n=y)

    for i in range(n):
        setattr(chain, f"r{i}", sp.resistor(r=chain.r)(p=chain.mid[i], n=chain.mid[i + 1]))
    return chain


def test_equal_values_give_the_same_cell():
    assert chain(n=3) is chain(n=3)
    assert chain() is chain(n=2)
    assert chain(n=3) is not chain(n=4)


def test_the_format_names_the_cell():
    assert h.info(chain(n=3)).name == "chain_n3"
    assert chain(n=3).__name__ == "chain_n3"


def test_a_generated_cell_is_an_ordinary_cell():
    class Top(h.Subckt):
        a, y, gnd = h.Signals(3)
        i0 = chain(n=2)(r=2e3)(a, y, gnd)
        i1 = chain(n=2)()(y, a, gnd)
        vs = sp.vsource(type="dc", dc=1)(a, gnd)

    netlist = h.elaborate(Top)
    assert [cell.name for cell in netlist.cells].count("chain_n2") == 1
    assert "i0 (a y gnd) chain_n2 r=2e3" in spectre.write(netlist)


def test_build_parameters_never_reach_the_ir():
    chain_cell = next(c for c in h.elaborate(chain(n=2)).cells if c.name == "chain_n2")
    assert isinstance(chain_cell, ir.Subckt)
    assert [decl.name for decl in chain_cell.params] == ["r"]


def test_the_format_uses_every_argument():
    with pytest.raises(h.HdlError, match="doesn't use the argument 'w'"):

        @h.generator("inv_{n}")
        def missing(*, n: int, w: int) -> type[h.Subckt]:
            raise AssertionError

    with pytest.raises(h.HdlError, match="uses 'w', not an argument"):

        @h.generator("inv_{n}_{w}")
        def unknown(*, n: int) -> type[h.Subckt]:
            raise AssertionError

    @h.generator("inv_{size.nf}")
    def by_size(size: Size) -> type[h.Subckt]:
        class c(h.Subckt):
            a = h.Port()

        return c

    assert h.info(by_size(Size(nf=2))).name == "inv_2"
    assert by_size(Size(nf=2)) is by_size(Size(nf=2))


@pytest.mark.parametrize("bad", ["{", "x{}", "x{0}"])
def test_bad_formats(bad):
    with pytest.raises(h.HdlError):

        @h.generator(bad)
        def g(*, n: int) -> type[h.Subckt]:
            raise AssertionError


def test_a_format_is_required():
    with pytest.raises(h.HdlError, match="needs a name format"):

        @h.generator  # ty: ignore[invalid-argument-type]
        def g(*, n: int) -> type[h.Subckt]:
            raise AssertionError


def test_no_parameters_or_variable_arguments():
    with pytest.raises(h.HdlError, match="write a class"):

        @h.generator("x")
        def nothing() -> type[h.Subckt]:
            raise AssertionError

    with pytest.raises(h.HdlError, match="can't be checked"):

        @h.generator("x_{n}")
        def variable(n: int, **rest: int) -> type[h.Subckt]:
            raise AssertionError


def test_a_clash_names_both_calls():
    @h.generator("inv_{w:03.0f}")
    def rounded(w: float) -> type[h.Subckt]:
        class c(h.Subckt):
            a = h.Port()

        return c

    rounded(w=1.1)
    with pytest.raises(h.HdlError, match=r"w=1\.1 and w=1\.2 both 'inv_001'") as error:
        rounded(w=1.2)
    assert len(error.value.sources) == 2


def test_a_name_must_be_an_identifier():
    @h.generator("inv_{w}")
    def sized(*, w: float) -> type[h.Subckt]:
        class c(h.Subckt):
            a = h.Port()

        return c

    with pytest.raises(h.HdlError, match="not an identifier"):
        sized(w=1.5)
    assert h.info(sized(w=2)).name == "inv_2"


def test_arguments_are_checked():
    with pytest.raises(h.HdlError, match="generator chain"):
        chain(m=2)  # ty: ignore[unknown-argument]


def test_build_parameters_are_hashable():
    @h.generator("g_{v}")
    def g(*, v: object) -> type[h.Subckt]:
        raise AssertionError

    with pytest.raises(h.HdlError, match="isn't hashable"):
        g(v=[1])


def test_a_new_subckt_is_returned():
    class existing(h.Subckt):
        a = h.Port()

    @h.generator("old_{n}")
    def old(*, n: int) -> type[h.Subckt]:
        return existing

    with pytest.raises(h.HdlError, match="already existed"):
        old(n=1)
    assert h.info(existing).name == "existing"

    @h.generator("other_{n}")
    def other(*, n: int) -> type[h.Subckt]:
        return chain(n=n)

    with pytest.raises(h.HdlError, match="already existed"):
        other(n=2)

    @h.generator("wrong_{n}")
    def wrong(*, n: int) -> h.External:
        return sp.resistor

    with pytest.raises(h.HdlError, match="must return a new subckt"):
        wrong(n=1)


def test_recursion_with_the_same_values():
    @h.generator("loop_{n}")
    def loop(*, n: int) -> type[h.Subckt]:
        loop(n=n)
        raise AssertionError

    with pytest.raises(h.HdlError, match="calls itself with the same values"):
        loop(n=1)


def test_recursion_with_other_values():
    @h.generator("tree_{n}")
    def tree(*, n: int) -> type[h.Subckt]:
        class c(h.Subckt):
            a, y = h.Ports(2)

        if n > 0:
            c.sub = tree(n=n - 1)()(c.a, c.y)
        return c

    assert [cell.name for cell in h.elaborate(tree(n=2)).cells] == ["tree_0", "tree_1", "tree_2"]


def test_new_subckt_works_in_a_generator():
    @h.generator("made_{n}")
    def made(*, n: int):
        m = h.new_subckt("anything")
        m.a = h.Port(width=n)
        return m

    assert h.info(made(n=2)).name == "made_2"
