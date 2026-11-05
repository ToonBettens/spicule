# spicule.sim: specification

A netlist says what the circuit is. A simulation says what to do with it: which
models to load, which analyses to run, what to save. The same circuit also goes
to LVS, so the two stay apart (`ir-decisions.md`, R-21). The model is the
dataclasses in `src/spicule/sim/model.py`. It depends only on `spicule.ir`.

```python
from spicule import sim
from spicule.dialects import spectre

tran = sim.Analysis("tr", "tran", stop=1e-9)
run = sim.Simulation(
    h.elaborate(tb),
    top="tb",
    ground="gnd",
    params={"vdd": 0.7},
    includes=[sim.Include("models.scs", section="tt")],
    options=sim.Options("opts", temp=27, reltol=1e-4),
    saves=["y", "dut.mid"],
    raw=["ic y=0"],
    analyses=[
        sim.Analysis("op", "dc"),
        sim.Analysis("sw", "sweep", param="vdd", values=[0.6, 0.8], children=[tran]),
    ],
)
text = spectre.write(run)
```

## 1. The fields of a simulation

| Field | Holds |
| --- | --- |
| `netlist` | The circuit, an `ir.Netlist`. Only the cells below `top` are part of the simulation |
| `top` | The subcircuit that is the circuit. Its instances go at the top level of the deck |
| `ground` | The net of `top` that is the reference node, so `0` in Spectre (R-12) |
| `params` | New values for parameters that `top` declares, as a dict |
| `includes` | Files to include: `sim.Include(path, section=None)` |
| `options` | The simulator's options, `sim.Options(name, **parameters)`, or `None` |
| `saves` | What to save, in the simulator's spelling. Written as given |
| `raw` | Simulator text before the options, written as given. An item can have several lines |
| `analyses` | The analyses in order: `sim.Analysis`, or `sim.Raw` for text whose place among them matters |

`ground` and `top` are required. A simulation without a reference node doesn't
run.

## 2. Analyses

`sim.Analysis(name, type, *, children=(), **parameters)` is one open structure.
The simulator owns the types and the names of their parameters, so spicule has
no class per analysis. A dialect refuses a type it doesn't know, so `trann` is
caught when writing. A wrong parameter name is caught by the simulator.

`children` holds the analyses that a sweep or a Monte Carlo run repeats, and
`sim.Raw` can be among them.

## 3. Values

A parameter of an analysis or of the options is one of:

| Given | Held as |
| --- | --- |
| `int`, `float`, `Decimal` | An exact number. A float goes through its shortest text: `1.6e-08` is exactly 16e-9 |
| `ir.Expression` | Itself: `ir.expr("2*vdd")` |
| `str` | A text |
| a list or a tuple of those | A list. It holds at least one value |

A value in `params` is a number or an expression, as any subckt parameter is. A
`str` is refused there, even `"3"`.

## 4. Rules

`sim.validate(simulation)` raises `sim.SimulationError` at the first broken
rule, after `ir.validate` of the netlist. Writers validate first.

| Rule | Text |
| --- | --- |
| S-1 | `netlist` is a `Netlist`, and `top` names a `Subckt` of it. |
| S-2 | `ground` names a scalar net of `top`. |
| S-3 | A name in `params` is declared by `top`. Its value refers only to parameters declared before it, as a default does (A-5). |
| S-4 | `options` is an `Options`, and `analyses` and `children` hold `Analysis` and `Raw`. Names, types and parameter names are identifiers. A list has at least one value. |
| S-5 | The instances of `top`, the options and the analyses have different names. So do the children of one analysis. |
| S-6 | `includes` holds `Include`. A path is one line of text, and a section is an identifier. |
| S-7 | A save is one name without spaces. Raw text isn't empty. |

## 5. The Spectre deck

`spectre.write` takes a `Netlist`, which becomes a library of subcircuits, or a
`Simulation`, which becomes a deck in this order:

| # | Part | Why here |
| --- | --- | --- |
| 1 | `simulator lang=spectre` | Must come first |
| 2 | Top-level `parameters` | Includes and the circuit may use them |
| 3 | `include`s | |
| 4 | The subcircuits below `top`, then the instances of `top` | |
| 5 | `raw` | Declarations: `statistics`, `ic`, `nodeset` |
| 6 | Options and saves | |
| 7 | Analyses | Last, in the given order |

The known types are `ANALYSES` in `dialects/spectre/syntax.py`, from what
`spectre -h` lists as analyses and controls. `options` has its own field, and
`altergroup` holds a circuit, so it goes in `raw`. Only `sweep` and `montecarlo`
take children, written as a `{ }` block. In a list, anything but a number, a
parameter or a unary of those gets parentheses, as Spectre asks: `values=[1 -w
(2*w)]`.

`cdl.write` takes a netlist only, because LVS has no analyses.

## 6. The simulation file

`jsonio.write` and `jsonio.read` take and give a simulation too. The rules of
the netlist file hold (`ir-spec.md`, section 10). The top level has `"format":
"spicule.sim/1"`, the circuit under `"netlist": {"cells": [...]}`, then the
fields above.

| Value | `kind` | Other fields |
| --- | --- | --- |
| Item of `analyses` or `children` | `analysis` | `name`, `type`, `params`, `children` |
| Item of `analyses` or `children` | `raw` | `text` |
| Parameter value | `expression`, `text` | `text` |
| Parameter value | `list` | `items`: values |

## 7. Not in this package

Starting a simulator, knowing where PDK files are, and reading results belong to
the run and flow code. A deck is plain text that can be run by hand.
