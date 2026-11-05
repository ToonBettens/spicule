"""The netlist file: round trips, and what isn't one."""

import json
import random

import pytest

import spicule.ir as ir
from spicule.dialects import jsonio


def num(text: str) -> ir.Expression:
    return ir.expr(text)


def conn(port: str, *pieces: ir.Piece) -> ir.Connection:
    return ir.Connection(port=port, pieces=pieces)


def design() -> ir.Netlist:
    nch = ir.External(
        name="nch",
        element=ir.Element.MOS,
        ports=(ir.Signal(name="d"), ir.Signal(name="b", range=ir.Range(msb=1, lsb=0))),
        meta=ir.Meta(origin="pdk.py:3"),
    )
    inv = ir.Subckt(
        name="inv",
        ports=(ir.Signal(name="a"), ir.Signal(name="q", range=ir.Range(msb=0, lsb=3))),
        params=(ir.ParamDecl(name="w", default=num("1e-6")), ir.ParamDecl(name="l", default=num("w/10"))),
        signals=(ir.Signal(name="mid"),),
        instances=(
            ir.Instance(
                name="m0",
                cell="nch",
                connections=(
                    conn("d", ir.SignalRef(signal="a")),
                    conn("b", ir.SignalRef(signal="q", range=ir.Range(msb=3, lsb=3)), ir.NoConnect(width=1)),
                ),
                params=(
                    ir.ParamValue(name="nfin", value=num("2*w")),
                    ir.ParamValue(name="flavor", value="lvt"),
                ),
                meta=ir.Meta(origin="design.py:12"),
            ),
            ir.Instance(
                name="m1",
                cell="nch",
                connections=(conn("d", ir.SignalRef(signal="mid")), conn("b", ir.NoConnect(width=2))),
            ),
        ),
        meta=ir.Meta(origin="design.py:8"),
    )
    return ir.Netlist(cells=(nch, inv))


def data() -> dict:
    return json.loads(jsonio.write(design()))


def test_a_round_trip_gives_an_equal_netlist():
    assert jsonio.read(jsonio.write(design())) == design()


def test_the_meta_survives():
    # `==` ignores meta, so this needs its own check.
    loaded = jsonio.read(jsonio.write(design()))
    nch, inv = loaded.cells
    assert nch.meta.origin == "pdk.py:3"
    assert isinstance(inv, ir.Subckt)
    assert inv.meta.origin == "design.py:8"
    assert inv.instances[0].meta.origin == "design.py:12"
    assert inv.instances[1].meta.origin is None


def test_the_file_follows_the_dataclasses():
    written = data()
    assert written["format"] == "spicule.ir/1"
    nch, inv = written["cells"]
    assert nch == {
        "kind": "external",
        "name": "nch",
        "element": "mos",
        "ports": [{"name": "d", "range": None}, {"name": "b", "range": {"msb": 1, "lsb": 0}}],
        "meta": {"origin": "pdk.py:3"},
    }
    m0 = inv["instances"][0]
    assert m0["connections"][1]["pieces"] == [
        {"kind": "signal_ref", "signal": "q", "range": {"msb": 3, "lsb": 3}},
        {"kind": "no_connect", "width": 1},
    ]
    assert m0["params"] == [
        {"name": "nfin", "value": {"kind": "expression", "text": "2*w"}},
        {"name": "flavor", "value": {"kind": "text", "text": "lvt"}},
    ]
    assert inv["instances"][1]["params"] == []  # every field is always written


def test_one_netlist_gives_one_file():
    assert jsonio.write(jsonio.read(jsonio.write(design()))) == jsonio.write(design())


def _random_tree(rng: random.Random, depth: int) -> ir.Expr:
    if depth == 0 or rng.random() < 0.2:
        return (
            ir.ParamRef(name="w")
            if rng.random() < 0.5
            else ir.Number(value=ir.parse_number(rng.choice(["0", "2", "1.5e-6", "7"])))
        )
    choice = rng.randrange(3)
    if choice == 0:
        return ir.Neg(operand=_random_tree(rng, depth - 1))
    if choice == 1:
        return ir.Binary(op=rng.choice("+-*/"), left=_random_tree(rng, depth - 1), right=_random_tree(rng, depth - 1))  # ty: ignore[invalid-argument-type]
    function, arity = rng.choice([("sqrt", 1), ("pow", 2), ("max", 2)])
    return ir.Call(function=function, args=tuple(_random_tree(rng, depth - 1) for _ in range(arity)))


def test_any_expression_survives_as_text():
    rng = random.Random(1)
    for _ in range(300):
        expression = ir.Expression(root=_random_tree(rng, 4))
        assert ir.parse_expression(ir.format_expression(expression)) == expression


def test_only_a_valid_netlist_is_written():
    with pytest.raises(ir.ValidationError):
        jsonio.write(ir.Netlist())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(format="other"), "format is 'other'"),
        (lambda d: d.update(format="spicule.ir/2"), "format is 'spicule.ir/2'"),
        (lambda d: d.pop("cells"), "missing field 'cells'"),
        (lambda d: d.update(extra=1), "unknown field 'extra'"),
        (lambda d: d.update(cells={}), "expected a list"),
        (lambda d: d["cells"][0].update(kind="other"), "unknown cell kind"),
        (lambda d: d["cells"][0].update(element="other"), "unknown element"),
        (lambda d: d["cells"][1]["ports"][0].pop("range"), "cells\\[1\\].ports\\[0\\]: missing field 'range'"),
        (
            lambda d: d["cells"][1]["instances"][0]["connections"][0]["pieces"][0].update(kind="other"),
            "unknown piece kind",
        ),
        (lambda d: d["cells"][1]["instances"][0]["params"][0]["value"].update(kind="other"), "unknown value kind"),
        (lambda d: d["cells"][1]["instances"][0]["params"][0]["value"].update(text="2*("), "params\\[0\\].value"),
        (lambda d: d["cells"][1]["instances"][0]["params"][0]["value"].update(text=2), "expected text"),
        (lambda d: d["cells"][1]["params"][0].update(default={"kind": "text", "text": "tt"}), "is a number"),
    ],
)
def test_what_is_no_netlist_file(change, message):
    written = data()
    change(written)
    with pytest.raises(jsonio.FormatError, match=message):
        jsonio.read(json.dumps(written))


def test_not_json():
    with pytest.raises(jsonio.FormatError, match="not JSON"):
        jsonio.read("{")
    with pytest.raises(jsonio.FormatError, match="file: expected an object"):
        jsonio.read("[]")


def test_a_file_that_breaks_a_rule():
    written = data()
    written["cells"][1]["instances"][0]["cell"] = "missing"
    with pytest.raises(ir.ValidationError, match="D-1"):
        jsonio.read(json.dumps(written))
    written = data()
    written["cells"][0]["ports"][1]["range"]["msb"] = "1"
    with pytest.raises(ir.ValidationError, match="F-1"):
        jsonio.read(json.dumps(written))
