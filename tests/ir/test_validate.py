"""The validator, part 1: field rules (F-1 to F-6), names (N-1 to N-4), references (D-1, D-2).

One valid netlist, and per rule small changes to it that break exactly that rule.
"""

import dataclasses
from decimal import Decimal

import pytest

import spicule.ir as ir


def num(text: str) -> ir.Expression:
    return ir.Expression(root=ir.Number(value=Decimal(text)))


NCH = ir.External(
    name="nch",
    element=ir.Element.MOS,
    ports=tuple(ir.Signal(name=n) for n in ("d", "g", "s", "b")),
    params=(
        ir.ParamDecl(name="w", type=ir.ParamType.NUMBER),
        ir.ParamDecl(name="m", type=ir.ParamType.NUMBER, default=num("1")),
    ),
)


def mos(name: str, d: str, g: str, s: str) -> ir.Instance:
    return ir.Instance(
        name=name,
        cell="nch",
        connections=tuple(
            ir.Connection(port=p, pieces=(ir.Slice(signal=n),)) for p, n in (("d", d), ("g", g), ("s", s), ("b", s))
        ),
        params=(ir.ParamValue(name="w", value=num("1e-6")),),
    )


PAIR = ir.Subckt(
    name="pair",
    ports=(ir.Signal(name="a"), ir.Signal(name="y", range=ir.Range(msb=1, lsb=0)), ir.Signal(name="vss")),
    params=(ir.ParamDecl(name="wn", type=ir.ParamType.NUMBER, default=num("1e-6")),),
    signals=(ir.Signal(name="mid"),),
    instances=(mos("m0", "mid", "a", "vss"), mos("m1", "mid", "a", "vss")),
)

TB = ir.Subckt(
    name="tb",
    signals=(ir.Signal(name="a"), ir.Signal(name="gnd"), ir.Signal(name="q", range=ir.Range(msb=1, lsb=0))),
    instances=(
        ir.Instance(
            name="dut",
            cell="pair",
            connections=(
                ir.Connection(port="a", pieces=(ir.Slice(signal="a"),)),
                ir.Connection(port="y", pieces=(ir.Slice(signal="q"),)),
                ir.Connection(port="vss", pieces=(ir.Slice(signal="gnd"),)),
            ),
        ),
    ),
)

VALID = ir.Netlist(cells=(NCH, PAIR, TB))


def rules(netlist: object) -> set[str]:
    return {v.rule for v in ir.check(netlist)}  # ty: ignore[invalid-argument-type]


def replace_cell(netlist: ir.Netlist, cell_name: str, /, **changes: object) -> ir.Netlist:
    cells = tuple(dataclasses.replace(c, **changes) if c.name == cell_name else c for c in netlist.cells)
    return dataclasses.replace(netlist, cells=cells)


def test_valid_netlist_has_no_violations():
    assert ir.check(VALID) == []
    ir.validate(VALID)


def test_validate_raises_with_every_violation():
    broken = replace_cell(VALID, "pair", signals=(ir.Signal(name="mid"), ir.Signal(name="a"), ir.Signal(name="a")))
    with pytest.raises(ir.ValidationError) as excinfo:
        ir.validate(broken)
    assert [v.rule for v in excinfo.value.violations] == ["N-2", "N-2"]
    assert "N-2" in str(excinfo.value)


# Field rules


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(dataclasses.replace(VALID, cells=list(VALID.cells)), id="list-not-tuple"),
        pytest.param(replace_cell(VALID, "nch", element="mos"), id="str-not-enum"),
        pytest.param(
            replace_cell(VALID, "pair", ports=(ir.Signal(name="a", range=ir.Range(msb=True, lsb=0)),)),
            id="bool-not-int",
        ),
        pytest.param(
            replace_cell(VALID, "pair", params=(ir.ParamDecl(name="wn", type=ir.ParamType.NUMBER, default=1.5),)),  # ty: ignore[invalid-argument-type]
            id="float-not-value",
        ),
        pytest.param(replace_cell(VALID, "pair", name=None), id="required-missing"),
        pytest.param("not a netlist", id="not-a-model-object"),
    ],
)
def test_f1_types(bad):
    assert rules(bad) == {"F-1"}


def test_f1_reports_the_path():
    bad = replace_cell(VALID, "pair", ports=(ir.Signal(name="a", range=ir.Range(msb=True, lsb=0)),))
    [v] = ir.check(bad)
    assert v.where == "cells[1].ports[0].range.msb"
    assert v.cell == "pair"


@pytest.mark.parametrize("name", ["1abc", "a-b", "", "a b", "d<3>"])
def test_f2_identifiers(name):
    assert rules(replace_cell(VALID, "pair", signals=(ir.Signal(name=name),))) == {"F-2"}


def test_f2_names_are_case_sensitive():
    assert rules(replace_cell(VALID, "pair", signals=(ir.Signal(name="mid"), ir.Signal(name="MID")))) == set()


def test_f3_bounds():
    assert rules(replace_cell(VALID, "tb", signals=(ir.Signal(name="q", range=ir.Range(msb=-1, lsb=0)),))) == {"F-3"}
    bad_nc = ir.Connection(port="y", pieces=(ir.NoConnect(width=0),))
    dut = dataclasses.replace(
        TB.instances[0], connections=(TB.instances[0].connections[0], bad_nc, TB.instances[0].connections[2])
    )
    assert rules(replace_cell(VALID, "tb", instances=(dut,))) == {"F-3"}


def test_f4_connection_has_a_piece():
    empty = ir.Connection(port="y", pieces=())
    dut = dataclasses.replace(
        TB.instances[0], connections=(TB.instances[0].connections[0], empty, TB.instances[0].connections[2])
    )
    assert rules(replace_cell(VALID, "tb", instances=(dut,))) == {"F-4"}


@pytest.mark.parametrize("number", ["inf", "-inf", "nan", "snan"])
def test_f5_finite_numbers(number):
    assert rules(
        replace_cell(VALID, "pair", params=(ir.ParamDecl(name="wn", type=ir.ParamType.NUMBER, default=num(number)),))
    ) == {"F-5"}


def with_default(root: ir.Expr) -> ir.Netlist:
    params = (ir.ParamDecl(name="l", type=ir.ParamType.NUMBER, default=ir.Expression(root=root)),)
    return replace_cell(VALID, "pair", params=params)


@pytest.mark.parametrize(
    "root",
    [
        pytest.param(
            ir.Binary(op="%", left=ir.Number(value=Decimal(1)), right=ir.Number(value=Decimal(2))),  # ty: ignore[invalid-argument-type]
            id="unknown-operator",
        ),
        pytest.param(ir.Call(function="log", args=(ir.Number(value=Decimal(1)),)), id="unknown-function"),
        pytest.param(ir.Call(function="max", args=(ir.Number(value=Decimal(1)),)), id="wrong-arity"),
    ],
)
def test_f6_operators_and_functions(root):
    assert rules(with_default(root)) == {"F-6"}


def test_f6_known_functions_pass():
    root = ir.Call(function="max", args=(ir.Number(value=Decimal(1)), ir.Neg(operand=ir.Number(value=Decimal(2)))))
    assert rules(with_default(root)) == set()


def test_f7_netlist_not_empty():
    assert rules(ir.Netlist()) == {"F-7"}


def test_semantic_rules_wait_for_field_rules():
    # A duplicate cell (N-1) and a bad name (F-2): only the field rule is reported.
    bad = dataclasses.replace(VALID, cells=(*VALID.cells, dataclasses.replace(NCH, ports=(ir.Signal(name="1d"),))))
    assert rules(bad) == {"F-2"}


# Names


def test_n1_cell_names_unique():
    assert rules(dataclasses.replace(VALID, cells=(NCH, NCH, PAIR, TB))) == {"N-1"}


def test_n1_is_case_sensitive():
    assert rules(dataclasses.replace(VALID, cells=(NCH, dataclasses.replace(NCH, name="NCH"), PAIR, TB))) == set()


def test_n2_ports_and_signals_share_a_namespace():
    assert rules(replace_cell(VALID, "pair", signals=(ir.Signal(name="mid"), ir.Signal(name="a")))) == {"N-2"}
    assert rules(replace_cell(VALID, "nch", ports=(*NCH.ports, ir.Signal(name="d")))) == {"N-2"}


def test_n3_instance_names_unique():
    assert rules(
        replace_cell(VALID, "pair", instances=(mos("m0", "mid", "a", "vss"), mos("m0", "mid", "a", "vss")))
    ) == {"N-3"}


def test_n4_parameter_names_unique():
    twice = (
        ir.ParamDecl(name="wn", type=ir.ParamType.NUMBER, default=num("1")),
        ir.ParamDecl(name="wn", type=ir.ParamType.STRING, default="x"),
    )
    assert rules(replace_cell(VALID, "pair", params=twice)) == {"N-4"}


# References


def test_d1_instances_name_existing_cells():
    dut = dataclasses.replace(TB.instances[0], cell="missing")
    [v] = ir.check(replace_cell(VALID, "tb", instances=(dut,)))
    assert (v.rule, v.cell, v.instance) == ("D-1", "tb", "dut")


def test_d2_define_before_use():
    assert rules(dataclasses.replace(VALID, cells=(NCH, TB, PAIR))) == {"D-2"}


def test_d2_no_self_instantiation():
    loop = ir.Instance(name="self", cell="pair")
    assert rules(replace_cell(VALID, "pair", instances=(*PAIR.instances, loop))) == {"D-2"}


def test_literal_inside_a_union_is_checked_not_crashing():
    from typing import Literal

    from spicule.ir.validate import _FieldChecker, _type_name

    tp = Literal["a", "b"] | None
    assert _type_name(tp) == "'a' | 'b' | None"
    checker = _FieldChecker()
    assert checker.check_type("a", tp, "x", None, None)
    assert checker.check_type(None, tp, "x", None, None)
    assert not checker.check_type("c", tp, "x", None, None)
    assert [v.rule for v in checker.violations] == ["F-1"]
