"""Expressions and numbers as text (spec 7.2, 7.3), and the parameter rules A-1 to A-6."""

from decimal import Decimal

import pytest

import spicule.ir as ir
from spicule.ir.expressions import param_refs

N = ir.Number
P = ir.ParamRef


def n(text: str) -> ir.Number:
    return N(value=Decimal(text))


def b(op: str, left: ir.Expr, right: ir.Expr) -> ir.Binary:
    return ir.Binary(op=op, left=left, right=right)  # ty: ignore[invalid-argument-type]


# Numbers


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("0", "0"),
        ("0.0", "0"),
        ("120", "120"),
        ("1", "1"),
        ("999", "999"),
        ("1000", "1e3"),
        ("4700", "4.7e3"),
        ("0.75", "750e-3"),
        ("0.001", "1e-3"),
        ("1.5e-6", "1.5e-6"),
        ("0.0000015", "1.5e-6"),
        ("1.5e-13", "150e-15"),
        ("2400000000", "2.4e9"),
        ("-1.5e-6", "-1.5e-6"),
        ("12345.678", "12.345678e3"),
    ],
)
def test_format_number_is_engineering_notation(text, canonical):
    assert ir.format_number(ir.parse_number(text)) == canonical
    assert ir.parse_number(canonical) == ir.parse_number(text)


@pytest.mark.parametrize("text", ["1u", "1k", "", "e3", "1.2.3", "inf", "nan"])
def test_parse_number_rejects(text):
    with pytest.raises(ir.ExpressionError):
        ir.parse_number(text)


# Parsing


@pytest.mark.parametrize(
    ("text", "tree"),
    [
        ("2*l", b("*", n("2"), P(name="l"))),
        ("a + b * c", b("+", P(name="a"), b("*", P(name="b"), P(name="c")))),
        ("a - b - c", b("-", b("-", P(name="a"), P(name="b")), P(name="c"))),
        ("2^3^2", b("^", n("2"), b("^", n("3"), n("2")))),
        ("-2^2", ir.Neg(operand=b("^", n("2"), n("2")))),
        ("2^-3", b("^", n("2"), ir.Neg(operand=n("3")))),
        ("+w", P(name="w")),
        ("(w)", P(name="w")),
        ("max(a, 2)", ir.Call(function="max", args=(P(name="a"), n("2")))),
        ("1.5e-6", n("1.5e-6")),
    ],
)
def test_parse_expression(text, tree):
    assert ir.parse_expression(text) == ir.Expression(root=tree)


def test_spelling_leaves_no_trace():
    assert ir.expr("w*2") == ir.expr(" w * 2 ") == ir.expr("(w)*2") == ir.expr("w*2.0")
    assert ir.expr("2*w") != ir.expr("w*2")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("2*", "unexpected end"),
        ("1u", "scale factors"),
        ("log(2)", "unknown function"),
        ("max(1)", "takes 2"),
        ("2 $ 3", "unexpected character"),
        ("(a", "unexpected end"),
        ("(a b", r"expected '\)'"),
        ("a b", "unexpected 'b'"),
    ],
)
def test_parse_errors(text, message):
    with pytest.raises(ir.ExpressionError, match=message):
        ir.parse_expression(text)


# Printing


@pytest.mark.parametrize(
    "text",
    [
        "2*l/w",
        "a + b*c",
        "(a + b)*c",
        "a - (b - c)",
        "a - b - c",
        "2^3^2",
        "(2^3)^2",
        "-2^2",
        "(-2)^2",
        "2^-3",
        "-(a + b)",
        "max(a, b + 1)",
        "1.5e-6*w",
        "a/(b*c)",
    ],
)
def test_format_round_trips_with_minimal_parentheses(text):
    expression = ir.parse_expression(text)
    assert ir.format_expression(expression) == text
    assert ir.parse_expression(ir.format_expression(expression)) == expression


def test_format_uses_canonical_numbers():
    assert ir.format_expression(ir.expr("0.0000015 * w")) == "1.5e-6*w"


def test_param_refs_in_order():
    assert param_refs(ir.expr("w*l + max(w, k)")) == ["w", "l", "k"]


def test_number_helper():
    assert ir.number("2") == ir.Expression(root=n("2"))
    assert ir.number(-3) == ir.expr("-3")
    assert ir.number(Decimal("0.075")) == ir.number("7.5e-2")


def test_negative_number_nodes_are_invalid():
    cell = ir.External(
        name="x",
        element=ir.Element.SUBCKT,
        params=(ir.ParamDecl(name="v", type=ir.ParamType.NUMBER, default=ir.Expression(root=n("-1"))),),
    )
    assert {v.rule for v in ir.check(ir.Netlist(cells=(cell,)))} == {"F-3"}


# Parameter rules


RES = ir.External(
    name="res",
    element=ir.Element.RESISTOR,
    ports=(ir.Signal(name="p"), ir.Signal(name="n")),
    params=(
        ir.ParamDecl(name="l", type=ir.ParamType.NUMBER),
        ir.ParamDecl(name="w", type=ir.ParamType.NUMBER, default=ir.expr("1e-6")),
        ir.ParamDecl(name="model", type=ir.ParamType.STRING, default="poly"),
    ),
)


def top(*params: ir.ParamValue, decls: tuple[ir.ParamDecl, ...] = ()) -> ir.Netlist:
    inst = ir.Instance(
        name="r1",
        cell="res",
        connections=(
            ir.Connection(port="p", pieces=(ir.Slice(signal="a"),)),
            ir.Connection(port="n", pieces=(ir.Slice(signal="b"),)),
        ),
        params=params,
    )
    cell = ir.Subckt(name="top", ports=(ir.Signal(name="a"), ir.Signal(name="b")), params=decls, instances=(inst,))
    return ir.Netlist(cells=(RES, cell))


L = ir.ParamValue(name="l", value=ir.expr("2e-6"))
LEN = (ir.ParamDecl(name="len", type=ir.ParamType.NUMBER, default=ir.expr("2e-6")),)


def rules(netlist: ir.Netlist) -> set[str]:
    return {v.rule for v in ir.check(netlist)}


def test_parameters_valid():
    assert ir.check(top(L)) == []
    assert ir.check(top(ir.ParamValue(name="l", value=ir.expr("2*len")), decls=LEN)) == []


def test_a1_only_declared_parameters():
    assert rules(top(L, ir.ParamValue(name="r", value=ir.expr("1")))) == {"A-1"}


def test_a2_each_parameter_once():
    assert rules(top(L, L)) == {"A-2"}


def test_a3_required_parameters_set():
    assert rules(top()) == {"A-3"}


def test_a4_value_types():
    assert rules(top(ir.ParamValue(name="l", value="2e-6"))) == {"A-4"}
    assert rules(top(L, ir.ParamValue(name="model", value=ir.expr("1")))) == {"A-4"}
    bad_default = (ir.ParamDecl(name="len", type=ir.ParamType.STRING, default=ir.expr("1")),)
    assert rules(top(L, decls=bad_default)) == {"A-4"}


def test_a5_instance_expressions_use_the_containing_cell():
    # `w` is a parameter of res, not of top: no inheritance.
    assert rules(top(ir.ParamValue(name="l", value=ir.expr("2*w")))) == {"A-5"}
    text_param = (ir.ParamDecl(name="len", type=ir.ParamType.STRING, default="x"),)
    assert rules(top(ir.ParamValue(name="l", value=ir.expr("2*len")), decls=text_param)) == {"A-5"}


def test_a6_defaults_use_earlier_parameters():
    later = (
        ir.ParamDecl(name="len", type=ir.ParamType.NUMBER, default=ir.expr("2*wid")),
        ir.ParamDecl(name="wid", type=ir.ParamType.NUMBER, default=ir.expr("1e-6")),
    )
    assert rules(top(L, decls=later)) == {"A-6"}
    earlier = (later[1], later[0])
    assert rules(top(L, decls=earlier)) == set()
