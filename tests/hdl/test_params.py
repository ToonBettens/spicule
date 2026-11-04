"""Netlist parameters and the expressions they build."""

from decimal import Decimal

import pytest

import spicule.hdl as h
import spicule.ir as ir
from spicule.hdl.params import as_number, to_value


def text(value: object) -> str:
    """An HDL value as canonical IR text, through the IR."""
    converted = to_value(value, "test", None)
    assert isinstance(converted, h.ParamExpr)
    return ir.format_expression(converted.to_ir())


def named(name: str, default: object = 1, **kwargs) -> h.Param:
    p = h.Param(default=default, **kwargs)
    p.__set_name__(None, name)
    return p


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (16e-9, "16e-9"),
        (0.3e-6, "300e-9"),
        (0.1, "100e-3"),
        (3, "3"),
        (-2, "-2"),
        (Decimal("4.70e3"), "4.7e3"),
    ],
)
def test_numbers_are_exact(value, expected):
    assert text(value) == expected


def test_negative_numbers_are_negations():
    expr = to_value(-1.5, "test", None)
    assert isinstance(expr, h.ParamExpr)
    assert expr.to_ir() == ir.Expression(root=ir.Neg(operand=ir.Number(value=Decimal("1.5"))))


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), None, [1]])
def test_bad_numbers(value):
    with pytest.raises(h.HdlError):
        to_value(value, "test", None)


def test_operators_build_trees():
    w, nf = named("w"), named("nf")
    assert text(2 * w) == "2*w"
    assert text(w * 2 + nf) == "w*2 + nf"
    assert text(w - (nf - 1)) == "w - (nf - 1)"
    assert text(1 / w) == "1/w"
    assert text(-w) == "-w"
    assert text(+w) == "w"
    assert text(h.fn.abs(w)) == "abs(w)"
    assert text(w**2) == "pow(w, 2)"
    assert text(2**w) == "pow(2, w)"
    assert text(h.fn.sqrt(w * nf)) == "sqrt(w*nf)"
    assert text(h.fn.max(w, 16e-9)) == "max(w, 16e-9)"
    assert text(h.fn.pow(w, 0.5)) == "pow(w, 500e-3)"


def test_refs_in_order_of_appearance():
    w, nf = named("w"), named("nf")
    expr = w * nf + w
    assert [p.name for p in expr.refs] == ["w", "nf"]


def test_expressions_have_no_truth_value():
    w = named("w")
    with pytest.raises(h.HdlError, match="truth value"):
        bool(w + 1)
    with pytest.raises(h.HdlError, match="truth value"):
        bool(w)


def test_subckt_parameters_are_numbers():
    with pytest.raises(h.HdlError, match="build parameter"):
        h.Param(default="tt")
    with pytest.raises(h.HdlError, match="build parameter"):
        as_number("1e-6", "test", None)  # a number in quotes is text
    assert to_value("tt", "test", None) == "tt"  # text only for external cells


def test_declaration_to_ir():
    p = named("w", default=2e-6)
    assert p.to_decl() == ir.ParamDecl(name="w", default=ir.number("2e-6"))
    assert p.to_ir() == ir.Expression(root=ir.ParamRef(name="w"))  # as an expression: a reference to itself


def test_every_parameter_has_a_default():
    with pytest.raises(TypeError, match="default"):
        h.Param()  # ty: ignore[missing-argument]
