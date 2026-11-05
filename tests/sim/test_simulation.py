"""A simulation: what its constructors hold, and the rules of docs/sim-spec.md."""

from decimal import Decimal

import pytest

import spicule.ir as ir
from spicule import sim


def resistor() -> ir.External:
    return ir.External(name="resistor", element=ir.Element.BUILTIN, ports=(ir.Signal(name="p"), ir.Signal(name="n")))


def netlist() -> ir.Netlist:
    unused = ir.Subckt(name="unused")
    leaf = ir.Subckt(
        name="leaf",
        ports=(ir.Signal(name="a"),),
        instances=(
            ir.Instance(
                name="r0",
                cell="resistor",
                connections=(
                    ir.Connection(port="p", pieces=(ir.SignalRef(signal="a"),)),
                    ir.Connection(port="n", pieces=(ir.SignalRef(signal="a"),)),
                ),
            ),
        ),
    )
    tb = ir.Subckt(
        name="tb",
        signals=(ir.Signal(name="gnd"), ir.Signal(name="bus", range=ir.Range(msb=1, lsb=0))),
        params=(ir.ParamDecl(name="vdd", default=ir.expr("1")), ir.ParamDecl(name="x", default=ir.expr("2*vdd"))),
        instances=(
            ir.Instance(
                name="dut", cell="leaf", connections=(ir.Connection(port="a", pieces=(ir.SignalRef(signal="gnd"),)),)
            ),
        ),
    )
    return ir.Netlist(cells=(resistor(), unused, leaf, tb))


def run(**kwargs) -> sim.Simulation:
    return sim.Simulation(netlist(), top=kwargs.pop("top", "tb"), ground=kwargs.pop("ground", "gnd"), **kwargs)


def test_a_simulation_is_valid():
    sim.validate(run(params={"vdd": 0.7}, analyses=[sim.Analysis("op", "dc")]))


def test_numbers_are_exact():
    tran = sim.Analysis("tr", "tran", stop=1.6e-08, start=0, step=Decimal("1e-12"))
    assert [param.value for param in tran.params] == [ir.expr("16e-9"), ir.expr("0"), ir.expr("1e-12")]


def test_values_can_be_negative_text_expressions_and_lists():
    tran = sim.Analysis("sw", "sweep", start=-1, param="vdd", stop=ir.expr("2*vdd"), values=[0.5, "x", ir.expr("1")])
    assert [param.value for param in tran.params] == [
        ir.expr("-1"),
        "vdd",
        ir.expr("2*vdd"),
        (ir.expr("500e-3"), "x", ir.expr("1")),
    ]


def test_spectre_parameter_names_can_be_those_of_the_constructor():
    analysis = sim.Analysis("a", "alter", name="x", type="y")
    assert (analysis.name, analysis.type) == ("a", "alter")
    assert [param.name for param in analysis.params] == ["name", "type"]


@pytest.mark.parametrize("value", [True, None, object(), float("inf"), float("nan"), [[1]]])
def test_values_that_cant_be_held(value):
    with pytest.raises(sim.SimulationError, match="parameter stop"):
        sim.Analysis("tr", "tran", stop=value)


def test_a_text_is_not_a_list():
    with pytest.raises(sim.SimulationError, match="saves: expected a list"):
        run(saves="out")
    with pytest.raises(sim.SimulationError, match="analyses: expected a list"):
        run(analyses=sim.Analysis("op", "dc"))


def test_the_same_simulation_is_equal_and_hashable():
    build = lambda: run(saves=["a"], options=sim.Options("o", temp=27), analyses=[sim.Analysis("op", "dc")])  # noqa: E731
    assert build() == build()
    assert hash(build().analyses) == hash(build().analyses)


def test_cells_are_the_ones_below_the_top():
    assert [cell.name for cell in run().cells] == ["leaf"]


def test_top_params_keep_their_order():
    params = run(params={"x": 3}).top_params
    assert [(decl.name, decl.default) for decl in params] == [("vdd", ir.expr("1")), ("x", ir.expr("3"))]


@pytest.mark.parametrize(
    ("kwargs", "rule", "message"),
    [
        ({"top": "nope"}, "S-1", "top 'nope'"),
        ({"top": "resistor"}, "S-1", "top 'resistor'"),
        ({"ground": "nope"}, "S-2", "ground 'nope'"),
        ({"ground": "bus"}, "S-2", "ground 'bus'"),
        ({"params": {"nope": 1}}, "S-3", "parameter 'nope' is not declared by 'tb' .declared: vdd, x."),
        ({"params": {"vdd": ir.expr("x")}}, "S-3", "'vdd' refers to x"),
        ({"params": {"x": ir.expr("nope")}}, "S-3", "'x' refers to nope"),
        ({"options": 3}, "S-4", "options: expected Options"),
        ({"options": sim.Options("a b")}, "S-4", "'a b' is not a name"),
        ({"options": sim.Options("o", values=[])}, "S-4", "a list has at least one value"),
        ({"analyses": [3]}, "S-4", "expected an Analysis or a Raw"),
        ({"analyses": [sim.Analysis("1a", "dc")]}, "S-4", "'1a' is not a name"),
        ({"analyses": [sim.Analysis("a", "d c")]}, "S-4", "'d c' is not a name"),
        ({"analyses": [sim.Analysis("a", "dc", **{"a b": 1})]}, "S-4", "'a b' is not a name"),
        ({"analyses": [sim.Analysis("a", "sweep", children=[3])]}, "S-4", "analysis a: expected"),  # ty: ignore[invalid-argument-type]
        ({"analyses": [sim.Analysis("a", "dc"), sim.Analysis("a", "tran")]}, "S-5", "'a' is used more than once"),
        ({"analyses": [sim.Analysis("dut", "dc")]}, "S-5", "'dut' is used more than once"),
        (
            {"options": sim.Options("o"), "analyses": [sim.Analysis("o", "dc")]},
            "S-5",
            "'o' is used more than once",
        ),
        (
            {"analyses": [sim.Analysis("s", "sweep", children=[sim.Analysis("a", "dc"), sim.Analysis("a", "dc")])]},
            "S-5",
            "analysis s: the name 'a'",
        ),
        ({"includes": [3]}, "S-6", "expected an Include"),
        ({"includes": [sim.Include("")]}, "S-6", "is not a path"),
        ({"includes": [sim.Include("m.scs", section="a b")]}, "S-6", "section 'a b'"),
        ({"saves": ["a b"]}, "S-7", "expected one name"),
        ({"saves": [""]}, "S-7", "expected one name"),
        ({"raw": [""]}, "S-7", "raw: expected text"),
        ({"analyses": [sim.Raw(" ")]}, "S-7", "raw: expected text"),
    ],
)
def test_rules(kwargs, rule, message):
    with pytest.raises(sim.SimulationError, match=rf"\[{rule}\].*{message}"):
        sim.validate(run(**kwargs))


def test_a_child_may_share_a_name_with_the_top_level():
    child = sim.Analysis("op", "dc")
    sim.validate(run(analyses=[sim.Analysis("op", "dc"), sim.Analysis("s", "sweep", children=[child])]))


def test_a_number_for_a_parameter_of_the_top_is_required():
    with pytest.raises(sim.SimulationError, match="number, got the text"):
        run(params={"vdd": "fast"})


def test_the_netlist_is_validated():
    bad = ir.Netlist(cells=())
    with pytest.raises(ir.ValidationError):
        sim.validate(sim.Simulation(bad, top="tb", ground="gnd"))
    with pytest.raises(sim.SimulationError, match="expected a Netlist"):
        sim.validate(sim.Simulation("netlist", top="tb", ground="gnd"))  # ty: ignore[invalid-argument-type]


def test_only_a_simulation_is_validated():
    with pytest.raises(sim.SimulationError, match="expected a Simulation"):
        sim.validate(netlist())  # ty: ignore[invalid-argument-type]
