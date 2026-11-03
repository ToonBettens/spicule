"""The model's conventions (spec section 1) and shape (section 2)."""

import dataclasses
from decimal import Decimal
from typing import get_args, get_origin, get_type_hints

import pytest

import spicule.ir as ir
from spicule.ir.model import MODEL_CLASSES


def num(text: str) -> ir.Expression:
    return ir.Expression(root=ir.Number(value=Decimal(text)))


@pytest.mark.parametrize("cls", MODEL_CLASSES, ids=lambda cls: cls.__name__)
def test_every_model_class_is_a_frozen_slotted_dataclass(cls):
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__
    assert params.frozen
    assert params.kw_only
    assert "__slots__" in cls.__dict__


@pytest.mark.parametrize("cls", MODEL_CLASSES, ids=lambda cls: cls.__name__)
def test_every_sequence_field_is_a_tuple(cls):
    for name, tp in get_type_hints(cls).items():
        origin = get_origin(tp)
        if origin in (list, tuple, set, frozenset, dict):
            assert origin is tuple, f"{cls.__name__}.{name}: {tp}"
            assert get_args(tp)[1] is Ellipsis, f"{cls.__name__}.{name}: {tp}"


def test_every_model_class_is_exported():
    assert {cls.__name__ for cls in MODEL_CLASSES} <= set(ir.__all__)


def test_numbers_compare_numerically():
    assert num("0.075") == num("7.5e-2")
    assert hash(num("0.075")) == hash(num("7.5e-2"))
    a = ir.Instance(name="r1", cell="res", params=(ir.ParamValue(name="r", value=num("1.5e-6")),))
    b = dataclasses.replace(a, params=(ir.ParamValue(name="r", value=num("0.0000015")),))
    assert a == b
    assert hash(a) == hash(b)


def test_meta_never_affects_equality():
    plain = ir.Instance(name="r1", cell="res")
    annotated = dataclasses.replace(plain, meta=ir.Meta(origin="tb/tb_inv.py:30"))
    assert plain == annotated
    assert hash(plain) == hash(annotated)
    assert annotated.meta.origin == "tb/tb_inv.py:30"
    assert plain.meta == ir.Meta()


def test_only_hierarchy_nodes_have_meta():
    with_meta = {cls for cls in MODEL_CLASSES if "meta" in {f.name for f in dataclasses.fields(cls)}}
    assert with_meta == {ir.Subckt, ir.External, ir.Instance}


def test_order_is_part_of_the_value():
    mp = ir.Instance(name="mp", cell="pch")
    mn = ir.Instance(name="mn", cell="nch")
    assert ir.Subckt(name="inv", instances=(mp, mn)) != ir.Subckt(name="inv", instances=(mn, mp))


def test_values_are_immutable():
    cell = ir.Subckt(name="a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cell.name = "b"  # ty: ignore[invalid-assignment]


def times(left: ir.Expr, right: ir.Expr) -> ir.Expression:
    return ir.Expression(root=ir.Binary(op="*", left=left, right=right))


def test_expressions_compare_structurally():
    w = ir.ParamRef(name="w")
    # `w*2`, `w * 2` and `(w)*2` all parse to this tree; `w*2.0` too, numbers compare numerically.
    assert times(w, ir.Number(value=Decimal("2"))) == times(w, ir.Number(value=Decimal("2.0")))
    assert hash(times(w, ir.Number(value=Decimal("2")))) == hash(times(w, ir.Number(value=Decimal("2.0"))))
    # No algebra: `2*w` is a different tree.
    assert times(w, ir.Number(value=Decimal("2"))) != times(ir.Number(value=Decimal("2")), w)


def test_expression_trees_nest():
    # The tree of `max(-w, 2*l)`.
    expr = ir.Expression(
        root=ir.Call(
            function="max",
            args=(
                ir.Neg(operand=ir.ParamRef(name="w")),
                ir.Binary(op="*", left=ir.Number(value=Decimal("2")), right=ir.ParamRef(name="l")),
            ),
        )
    )
    decl = ir.ParamDecl(name="x", type=ir.ParamType.NUMBER, default=expr)
    assert decl == dataclasses.replace(decl)
    assert len({decl, dataclasses.replace(decl)}) == 1


ENUMS = (ir.Element, ir.ParamType)


@pytest.mark.parametrize("enum", ENUMS, ids=lambda enum: enum.__name__)
def test_enums_have_lowercase_values(enum):
    for member in enum:
        assert member.value == member.name.lower()


@pytest.mark.parametrize("enum", ENUMS, ids=lambda enum: enum.__name__)
def test_enum_members_never_equal_strings(enum):
    for member in enum:
        assert member != member.value


def test_a_bare_string_makes_a_different_cell():
    real = ir.External(name="nch", element=ir.Element.MOS)
    assert ir.External(name="nch", element="mos") != real  # ty: ignore[invalid-argument-type]


def test_a_small_netlist():
    """A 4-bit output cell on a PDK device, and a testbench with a built-in source; leaves first."""
    nch = ir.External(
        name="nch",
        element=ir.Element.MOS,
        ports=tuple(ir.Signal(name=n) for n in ("d", "g", "s", "b")),
        params=(
            ir.ParamDecl(name="w", type=ir.ParamType.NUMBER),
            ir.ParamDecl(name="m", type=ir.ParamType.NUMBER, default=num("1")),
        ),
    )
    vdc = ir.External(
        name="vdc",
        element=ir.Element.BUILTIN,
        ports=(ir.Signal(name="p"), ir.Signal(name="n")),
        params=(ir.ParamDecl(name="dc", type=ir.ParamType.NUMBER, default=num("0")),),
    )
    four = ir.Range(msb=3, lsb=0)
    mn = ir.Instance(
        name="mn",
        cell="nch",
        connections=(
            ir.Connection(port="d", pieces=(ir.Slice(signal="out", range=ir.Range(msb=0, lsb=0)),)),
            ir.Connection(port="g", pieces=(ir.Slice(signal="a"),)),
            ir.Connection(port="s", pieces=(ir.Slice(signal="vss"),)),
            ir.Connection(port="b", pieces=(ir.Slice(signal="vss"),)),
        ),
        params=(ir.ParamValue(name="w", value=num("1e-6")), ir.ParamValue(name="m", value=num("2"))),
    )
    bank = ir.Subckt(
        name="bank",
        ports=(ir.Signal(name="a"), ir.Signal(name="out", range=four), ir.Signal(name="vss")),
        instances=(mn,),
    )
    tb = ir.Subckt(
        name="tb",
        signals=(ir.Signal(name="a"), ir.Signal(name="gnd"), ir.Signal(name="q", range=ir.Range(msb=1, lsb=0))),
        instances=(
            ir.Instance(
                name="dut",
                cell="bank",
                connections=(
                    ir.Connection(port="a", pieces=(ir.Slice(signal="a"),)),
                    # Bus port `out<3:0>`: the whole 2-bit bus `q`, then two bits left open.
                    ir.Connection(port="out", pieces=(ir.Slice(signal="q"), ir.NoConnect(width=2))),
                    ir.Connection(port="vss", pieces=(ir.Slice(signal="gnd"),)),
                ),
            ),
            ir.Instance(
                name="v0",
                cell="vdc",
                connections=(
                    ir.Connection(port="p", pieces=(ir.Slice(signal="a"),)),
                    ir.Connection(port="n", pieces=(ir.Slice(signal="gnd"),)),
                ),
                params=(ir.ParamValue(name="dc", value=num("0.8")),),
            ),
        ),
    )
    netlist = ir.Netlist(cells=(nch, vdc, bank, tb))
    assert netlist == ir.Netlist(cells=(nch, vdc, dataclasses.replace(bank), tb))
    assert ir.Slice(signal="q") != ir.Slice(signal="q", range=four)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("a_1", True), ("_x", True), ("1a", False), ("a-b", False), ("", False), ("a\n", False), (3, False)],
)
def test_is_identifier(text, expected):
    assert ir.is_identifier(text) is expected
