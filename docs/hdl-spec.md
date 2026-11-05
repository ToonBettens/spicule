# spicule.hdl: specification

The HDL is what designers write: Python classes and functions that elaborate to
a validated `spicule.ir.Netlist`. This document describes the language. The
result it produces is specified in `ir-spec.md`.

```python
import spicule.hdl as h
```

## 0. Scope

The HDL describes cells, their nets and parameters, and how they connect. It
adds what the IR leaves to the producer: Python as the language around the
circuit, generators, and errors that point at Python lines. Analyses, includes
and options are not in the HDL. They belong to a simulation (`sim-spec.md`).

## 1. Conventions

1. **Explicit form and shortcuts.** Most things have one explicit form, which
   shows what happens. Shortcuts stand for it and never change the IR. Both stay
   valid. This document names the explicit form first.
2. **Checked where written.** A mistake is an `h.HdlError` that names the Python
   lines involved, as early as it can be known.
3. **Names are final.** A cell's name in the netlist is exactly its name here.
   The HDL never renames anything to make it unique (R-2).
4. **What is public.** `h.` exports what a design can see: what it writes, holds
   or catches. Everything else is internal.

## 2. At a glance

| HDL | IR | Section |
| --- | --- | --- |
| `class inv(h.Subckt)` | `Subckt(name="inv")` | 3 |
| `h.External("nch", h.MOS, "d g s b")` | `External(name="nch", element=MOS, ports)` | 4 |
| `a = h.Port()` | `Signal(a)` in `Subckt.ports` | 5 |
| `mid = h.Signal()` | `Signal(mid)` in `Subckt.signals` | 5 |
| `d = h.Port(width=4)` | `Signal(d, Range(3, 0))` | 5 |
| `nfin = h.Param(default=2)` | `ParamDecl(nfin, 2)` | 6 |
| `mn = nch(nfin=nfin)(d=y, ...)` | `Instance(mn, cell="nch", connections, params)` | 7 |
| `d[3:2]`, `h.Concat(...)`, `h.NoConn()` | `SignalRef`, a list of pieces, `NoConnect` | 5, 7 |
| `2 * nfin` | `Binary("*", Number(2), ParamRef(nfin))` | 6 |
| `@h.generator("inv_x{n}")` | one `Subckt` per distinct value | 8 |
| the Python line | `meta.origin` | 9 |

## 3. Subckts

A subckt is a class deriving from `h.Subckt`. The class name is the cell name.

```python
class inv(h.Subckt):
    a = h.Port()
    y = h.Port()
    vdd = h.Port()
    vss = h.Port()
    nfin = h.Param(default=2)
    mp = pch(nfin=2 * nfin)(d=y, g=a, s=vdd, b=vdd)
    mn = nch(nfin=nfin)(d=y, g=a, s=vss, b=vss)
```

Every public name in the class body is part of the cell, in the order written,
and must be a port, a signal, a parameter or an instance. A name starting with
`_` stays out of the cell. It is ordinary Python, for helpers: `_w = 2 * nfin`.

No object of class `inv` ever exists. The class is a description, and calling it
starts an instance (section 7).

The same cell can be built step by step, for contents that ordinary Python
decides:

```python
m = h.new_subckt("inv_x4")
m.a = h.Port()
```

The same rules apply to assigned attributes. Attributes can also be added to a
class-defined subckt. Attribute access on `new_subckt` cells is unknown to type
checkers, so nets are best kept in local variables. Changing a subckt after
`elaborate` doesn't touch a netlist already made.

`h.info(cell)` gives the contents of a subckt: `ports`, `signals`, `params`,
`instances`, `name`, `source`.

| Refused | Because |
| --- | --- |
| A public name that is anything else, such as `x = 2 * w` or `y = inv()` without connections | It would silently not be part of the cell |
| A public name assigned twice, in a class body or by attribute | The first would be lost, for example a device |
| One object under two names, or in two subckts | A net or instance has one name and one owner |
| Deriving from a subckt, deleting an attribute, calling `h.Subckt` itself | |

## 4. External cells

An external cell is defined elsewhere: in a PDK, in an IP netlist, or in the
simulator. Only its interface is declared, and its definition is never written.

```python
nch = h.External("nch", element=h.MOS, ports=[h.Port(name="d"), h.Port(name="g")])
```

`element` says how a netlist calls the cell: `h.SUBCKT`, `h.MOS`, `h.DIODE`,
`h.BIPOLAR`, `h.RESISTOR`, `h.CAPACITOR`, `h.INDUCTOR` or `h.BUILTIN`. Ports are
listed in pin order. An external cell has no class body, so a port gets its name
with `name=`.

Shortcuts: `element` and `ports` by position, and ports as one string or as a
list that may mix strings with `h.Port`s. A bus is `name[msb:lsb]`.

```python
nch = h.External("nch", h.MOS, "d g s b")
sram = h.External("sram", h.SUBCKT, "addr[5:0] clk")
bits = h.External("bits", h.SUBCKT, [f"d{i}" for i in range(4)])
```

Parameters of an external cell belong to the PDK or the simulator, with their
defaults and which ones are required. So they are not declared, and any may be
set (section 6).

**Built-ins** are in `spicule.hdl.builtins`, one module per dialect, with the
simulator's own names:

```python
from spicule.hdl.builtins import spectre as sp

vs = sp.vsource(type="dc", dc=0.8)(p=vdd, n=gnd)
```

## 5. Nets

`h.Port` is a pin of its subckt, and `h.Signal` an internal net. They are
declared the same way:

| Form | Net |
| --- | --- |
| `h.Port()` | a scalar |
| `h.Port(width=8)` | a bus `<7:0>` |
| `h.Port(msb=0, lsb=3)` | a bus `<0:3>`, expanding 0, 1, 2, 3 |

`width=1` is a one-bit bus `<0:0>`, not a scalar. Shortcut: `a, y = h.Ports(2)`
and `d, q = h.Signals(2, width=4)` give several new nets of one shape.

### 5.1 Indexing

A bus has real bit names, and indexing uses them, as in Cadence and Verilog. It
is inclusive on both ends and in the order written. **It is not a Python list
slice.**

```python
d = h.Port(msb=7, lsb=4)
d[5]  # d<5>
d[7:6]  # d<7:6>, two bits
d[4:7]  # d<4:7>, four bits, reversed
```

`d[0:3]` is four bits. Python's meaning would count positions upward, so the
upper nibble of `d<7:0>` on a port `x<3:0>` would arrive reversed, which no
width check can catch. With bit names it is simply `d[7:4]`.

Indexing gives an `h.Slice`, short for `h.Slice(d, 7, 6)`. A slice can be
indexed again, inside its own range. It only has a meaning as a connection, and
a public attribute can't hold one.

A bus unpacks into its bits, in expansion order: `*d`, or `b3, b2, b1, b0 = d`.
A slice does too.

| Refused | |
| --- | --- |
| Negative indices, open ends (`d[7:]`), steps | They would need a position or a Python meaning |
| An index outside the bus or slice | |
| Indexing or unpacking a scalar | |

## 6. Parameters

### 6.1 Build and netlist parameters

Two kinds exist. Build parameters are Python values that decide structure
(section 8). Netlist parameters are written into the netlist and evaluated by
the simulator. This section is about the second kind. Use them for numbers the
simulator may vary.

### 6.2 Declaring

A subckt declares `h.Param(default=2)`, or `h.Param(2)`. Every parameter has a
default, so no instance has to set it. Subckt parameters are numbers. A default
may use parameters declared before it. A text choice is a build parameter,
written as literal text on a device.

An instance of a subckt may only set declared parameters, to a number or an
expression. An instance of an external cell may set any parameter, and a `str`
is a text value: `vsource(type="dc")`.

### 6.3 Numbers

An `int` or `Decimal` is exact. A float is converted through its shortest text,
so `16e-9` stays exactly that. Bools, NaN, infinities and numbers in quotes are
refused as numbers. There are no scale factors (`2u`).

Arithmetic done in Python happens before the HDL sees the value: `0.1 + 0.2` is
written as `300.00000000000004e-3`. `Decimal` arithmetic stays exact.

### 6.4 Expressions

Python operators on parameters don't calculate. They build a tree, written out
for the simulator: `+ - * /`, unary `-`, and `**`, written as `pow`. Functions
are in `h.fn`: `abs`, `sqrt`, `exp`, `ln`, `log10`, `min`, `max`, `pow`.

```python
r0 = res(r=2 * nfin + w)(p=a, n=b)  # written as r=2*nfin + w
```

A `Param` is the smallest expression, and an expression over it is an
`h.ParamExpr`. An expression on an instance may only use parameters of the
subckt it is in. An expression has no truth value, so `if nfin > 2` is not
available: the simulator evaluates it, not Python.

## 7. Instances

Every cell is instantiated with two calls, parameters first and then
connections. So a port and a parameter may share a name.

```python
dut = inv(nfin=4)(a=a, y=y, vdd=vdd, vss=gnd)
buf = inv()(a=y, y=z, vdd=vdd, vss=gnd)
```

The first call gives an `h.CellCall`, the second an `h.Instance`. An instance is
complete when it is made, and never changes.

### 7.1 Connections

A connection is a net, a slice, an `h.NoConn()`, or an `h.Concat(...)`. Parts of
a concatenation are in expansion order, and its first bit meets the port's first
bit. Every port is connected exactly once, with exactly its width.

```python
u0 = latch()(d=h.Concat(mid[3:2], en, h.NoConn(1)), q=q, clk=clk)
```

`h.NoConn()` leaves bits open on purpose: writers give each bit a fresh net. It
takes the port's width, and needs an explicit one inside a concatenation.

Shortcuts:

- **A tuple is a concatenation:** `d=(mid[3:2], en, h.NoConn(1))`.
- **By position,** in the cell's port order, mixable with keywords: `inv()(a, y,
  vss=vss, vdd=vdd)`. A call that connects by position connects every port. Two
  ports of the same width can be swapped unnoticed, so this is best kept to
  small cells.
- **Unpacking** a bus over scalar ports, with position: `three()(*d)`.

### 7.2 Partial calls

An `h.CellCall` is a template. It can be called any number of times, and each
call makes a new instance. Two methods give a new template with more filled in,
so a template never changes:

```python
_n = nch(l=16e-9).preset(b=vss)
m0 = _n(d=y, g=a, s=vss)
m1 = _n.params(l=20e-9, nfin=4)(d=a, g=y, s=vss)
```

`.params` overrides a value that was already set, because a preset value is a
default. `.preset` connects ports for good: connecting one again is refused,
since wiring a port twice is almost always a mistake. In a class body a template
needs a `_` name.

| Refused | |
| --- | --- |
| A port the cell doesn't have, a parameter a subckt doesn't declare | With a hint if it belongs in the other call |
| A width that doesn't fit | Checked at the call |
| A port connected twice | |
| Connecting by position after a preset, too many, too few, or a port both ways | |
| A port left unconnected | Reported by `elaborate`. Use `h.NoConn()` for an open pin |
| A net of another subckt, or of no subckt | Reported by `elaborate` |

## 8. Generators

A class is one cell, and a decorated function is a family of cells. Its
arguments are the build parameters: Python values that decide structure. It runs
once per distinct value, and each gets its own cell. They never reach the IR.

```python
@h.generator("invbank_n{n}")
def invbank(*, n: int = 4) -> type[h.Subckt]:
    class bank(h.Subckt):
        d, q = h.Ports(2, width=n)
        vdd, vss = h.Ports(2)
        nfin = h.Param(4)

    for bit in range(n):
        setattr(bank, f"x{bit}", inv(nfin=bank.nfin)(bank.d[bit], bank.q[bit], bank.vdd, bank.vss))
    return bank


dut = invbank(n=4)(nfin=6)(din, mid, vdd, vss)
```

That is three calls, one per layer: build parameters, netlist parameters,
connections. `bank4 = invbank(n=4)` is an ordinary subckt, with the usual two.
Equal values give the same cell, defaults filled in, so `invbank()` is
`invbank(n=4)`.

**The name format** is required, in Python's format syntax, so `{n:02d}` works.
It looks like an f-string but has no `f`, because the values only exist when the
generator is called. It names the cell, whatever the class is called inside.

A value that changes the structure, or is text, is a build parameter. A number
the simulator may vary is a netlist parameter. A size can be either: one cell
for all sizes, or one cell per size.

| Refused | When |
| --- | --- |
| No format, a format that misses an argument or uses an unknown one | At the definition |
| No arguments (write a class), `*args` or `**kwargs` in the signature | At the definition |
| Wrong arguments, or an unhashable value (use a tuple) | At the call |
| A name that isn't an identifier, such as `inv_1.5` | At the call |
| Two values giving one name, as `{w:.0f}` can | At the second call, naming both |
| Returning anything but a new subckt | At the call |
| Calling itself with the same values | At the call |

A family of external cells needs no generator: `nch = {vt:
h.External(f"nch_{vt}", h.MOS, "d g s b") for vt in ("svt", "lvt")}`.

## 9. Elaboration

`h.elaborate(*tops, root=None, lint=False)` gives the `ir.Netlist` of the
subckts `tops` and every cell they use. It leaves the subckts unchanged. It

1. collects every cell, leaves first, and refuses cycles,
2. refuses two different cells with one name, naming both lines,
3. converts connections to canonical pieces and parameter values to expressions,
4. fills `meta.origin` of cells and instances with `file:line`,
5. validates the netlist against every rule of `ir-spec.md`.

Paths in `meta.origin` and in errors are relative to `root`, or else to the
file's project: the nearest directory with a `pyproject.toml`, or else the
directory above its top-level package. A generated cell's origin is the `class`
line inside the generator.

Nothing about the netlist's dialect is chosen here. Writers take the netlist,
which they write as a library of subcircuits. A testbench to run is a simulation
of the netlist (`sim-spec.md`):

```python
netlist = h.elaborate(tb)
library = spectre.write(netlist)
deck = spectre.write(sim.Simulation(netlist, top="tb", ground="gnd"))
```

**Ground** is an ordinary net in the HDL. The simulation's `ground=` names it
(R-12).

## 10. Errors and warnings

`h.HdlError` has the message, and `sources`: the `h.Source` lines involved, in a
`file:line` form. A rule the netlist breaks is reported the same way, at the
lines of the cells and instances involved. The HDL checks what it can on the
spot, so a design normally doesn't get that far.

`lint=True` also warns about floating nets (W-1 to W-3) as `h.HdlWarning`,
through Python's `warnings`: printed by default, filterable, testable with
`pytest.warns`. They don't make the netlist invalid.
