# spicule.ir v1: specification

The model is the Python dataclasses in `src/spicule/ir/model.py`. This document
describes the model and numbers every rule a valid `Netlist` follows. The reasoning
behind it, and the alternatives that were weighed, are in `ir-decisions.md`.

## 0. Scope

The IR is the circuit part of a SPICE deck in structured, dialect-neutral form:
subcircuits, instances, nets and parameters. Producers (spicule HDL, netlist readers),
consumers (SPICE writers, data-out and analysis tools) read it.

## 1. Conventions

1. **Required and absent.** A required field is a required constructor
   argument. An optional field is `None` when absent. Sequences are tuples
   (empty has meaning). A field holding one of several kinds is a union.
2. **Immutable values.** Every class is a frozen, slotted, keyword-only
   dataclass. Enums are plain `Enum`s with lowercase values.
3. **Order is part of the value.** Tuples compare in order, so two netlists
   that list the same instances in a different order are different values.
   Producers emit in a deterministic order and every tool preserves it.
   Port order is also pin order, and piece order is also bit order.
   Order-insensitive comparison comes as its own independent helper function.
4. **Equality is circuit equality**, with these refinements:
   - `meta` fields are ignored.
   - numbers are `Decimal` and compare numerically, wherever they appear in an
     expression (`1.5e-6 == 0.0000015`).
   - connections are stored such that electrically equivalent wiring compares equally (`==`).
   - expressions are trees and compare structurally (`w*2 == w * 2 == (w)*2`, `2.0*w == 2*w`).
5. **Versioning.** JSON carries `"version": 1`. Within version 1 only additive
   changes. Readers reject unknown versions.
6. **Rules.** Every rule has an id: a letter for its group and a number. Field
   rules look at one value at a time. Semantic rules compare values and follow
   references, and are only checked on netlists that pass every field rule.
   Writers accept only validated netlists.

   | Group | Kind | Section | About |
   | --- | --- | --- | --- |
   | F-1 to F-7 | field | 9 | types, identifiers, bounds, finite numbers, operators and functions, a non-empty netlist |
   | N-1 to N-4 | semantic | 3 | unique names |
   | D-1, D-2 | semantic | 4 | references between cells, define before use |
   | C-1 to C-5 | semantic | 6 | connections and their canonical form |
   | A-1 to A-5 | semantic | 7 | parameters and expressions in scope |
   | W-1 to W-3 | warning | 6.4 | floating nets, reported while the netlist stays valid |

## 2. The model at a glance

```
Netlist(cells)                                            cells: Subckt | External, leaves first
Subckt(name, ports, params, signals, instances, meta)     defined here: a .subckt
External(name, element, ports, meta)                      defined elsewhere
    ports:   Signal(name, range?)                         the pins, in pin order
    params:  ParamDecl(name, type, default)               Subckt only
    signals: Signal(name, range?)                         internal nets only
Instance(name, cell, connections, params, meta)           cell: the instantiated cell's name
    connections: Connection(port, pieces)
    pieces:      SignalRef(signal, range?) | NoConnect(width)
    params:      ParamValue(name, value)
Range(msb, lsb)
Meta(origin?)                                             annotations, never affect meaning
Value = Expression(root) | str
    root: Number(value) | ParamRef(name) | Neg(operand) | Binary(op, left, right) | Call(function, args)
```

## 3. Names

Every identifier matches `[A-Za-z_][A-Za-z0-9_]*`. Names are case-sensitive.

| Rule | |
| --- | --- |
| N-1 | Cell names are unique in the netlist. |
| N-2 | Port and internal signal names are unique together within their cell. |
| N-3 | Instance names are unique within their cell. |
| N-4 | Parameter names are unique within their cell. |

Reserved keywords or case-insensitivity are checks consumers are responsible for.

## 4. Cells and references

A netlist holds one or more top cells and every cell they use, each once,
leaves first. Every instantiated cell is in it: `Subckt`s defined here, and PDK
devices, foreign subcircuits and built-ins as `External` cells.

A cell's name is its identity and is final: an instance names its cell.

| Rule | |
| --- | --- |
| D-1 | Every `Instance.cell` is the name of a cell in the netlist. |
| D-2 | Define before use: an instantiated cell comes earlier in `Netlist.cells` than the cell containing the instance. |

## 5. External cells

A netlist can use cells whose contents it doesn't contain: PDK devices, IP
blocks and standard cells defined in other netlist files, and the simulator's
own elements. The files that define them (PDK model libraries, IP netlists) are
pulled in by include directives, which belong to the simulation setup, not to
the IR.

Such a cell is still instantiated like any other. For that the netlist needs
its interface (name and ports in pin order) and nothing else: an `External`
cell is exactly that interface, without contents. Its parameters are not
declared (section 7.1).

To call it, a writer must know what kind of thing the name refers to, because
many SPICE dialects write a different instance line for each: the first letter
of the instance name (the element letter) tells the simulator whether `nch`
is a subcircuit (`X`) or a transistor model (`M`). `element` records this:

| `element` | The name refers to | Instance line |
| --- | --- | --- |
| `subckt` | a subcircuit defined in an included file | `X1 a b c name` |
| `mos` | a transistor model in an included file | `M1 d g s b name w=...` |
| `diode`, `bipolar` | a diode or bipolar model | `D1 ...`, `Q1 ...` |
| `resistor`, `capacitor`, `inductor` | a resistor, capacitor or inductor model | `R1 a b name ...` (C, L) |


**Built-ins** are elements the simulator provides itself, without any included
file, such as an ideal resistor or a voltage source. They have `element`
`builtin`, and the name is the simulator's own name for the element, with the
simulator's own parameters. Each dialect ships its built-ins as a declarations
module next to its writer, and its writer rejects a built-in name it doesn't
know.

## 6. Nets and connections

### 6.1 Signals and buses

A `Signal` without `range` is a scalar net. With a range (even `<0:0>`) it is a
bus. `Range(msb, lsb)` is defined as: `msb` is the left index, `lsb` the
right one, either may be larger, both `>= 0`. A range expands left to right:
`<3:0>` is bits 3, 2, 1, 0 and `<0:3>` is 0, 1, 2, 3. A bus port contributes its
bits to the pin list in expansion order.

Writers spell bus bits per dialect (`d<3>`, `d\<3\>`, ...).

### 6.2 Connections

An instance's `Connection` gives, for one port of the instantiated cell, a list
of pieces in expansion order. The pieces' bits, concatenated, meet the port's
bits first to first. A piece is:

- `SignalRef(signal, range?)`: bits of a port or internal signal of the
  containing `Subckt`. No range: the whole signal (scalar or whole bus). With
  a range: those bits, in either direction (`d<0:3>` of a `d<3:0>` bus). A
  single bit is written `<5:5>`.
- `NoConnect(width)`: `width` bits deliberately left open. Writers give each
  bit a unique net.

| Rule | |
| --- | --- |
| C-1 | Every port of the instantiated cell is connected exactly once, and every connection names a port of that cell. |
| C-2 | `SignalRef.signal` is a port or internal signal of the containing `Subckt`. |
| C-3 | A `SignalRef.range` is only set on a bus signal and lies within its declared range. |
| C-4 | The pieces' widths add up to the port's width (whole scalar: 1, whole bus: its width, range: `abs(msb-lsb)+1`). |

### 6.3 Canonical form

Every connection has exactly one representation. To get it, flatten the pieces
to bits, then rebuild them left to right, each time taking the longest run:

- Consecutive bits of one bus that step by +1 or -1 throughout form one
  `SignalRef`, and a run that is exactly the whole bus in its declared
  direction is written without range.
- A bit of a scalar signal is a piece on its own.
- Consecutive open bits form one `NoConnect`.

| Rule | |
| --- | --- |
| C-5 | Pieces are in canonical form. |

`canonicalize()` implements it, and every producer calls it. Example: with
`d<7:0>` declared, bits `d<3> d<2> d<5> d<6> NC NC` are the pieces `d<3:2>`,
`d<5:6>`, `NoConnect(2)`.

### 6.4 Floating nets

Floating nets are reported as warnings, not rule violations: the netlist stays
valid. Bits of a `NoConnect` don't count as connections.

| Warning | |
| --- | --- |
| W-1 | An internal signal is not connected to anything. |
| W-2 | A port bit is not used by any instance inside its cell. |
| W-3 | A bit of an internal signal is connected fewer than twice (and the signal is not entirely unused, which is W-1). |

## 7. Parameters

Netlist parameters are written into the netlist and evaluated by the simulator.
Build parameters (the Python inputs of generators) never reach the IR.

### 7.1 Declarations and values

A `Subckt` declares `ParamDecl(name, type, default)`. The type is `number` or
`string`. Every parameter has a default, so an instance never has to set one.
An instance sets `ParamValue(name, value)`. The value of a number parameter is
always an `Expression`. A plain number is the smallest expression,
`Expression(Number(...))`. The value of a string parameter is a `str`.
Multiplicity `m` is an ordinary parameter: a subckt that accepts it declares
it.

An `External` declares no parameters. They are open: the cell is defined
elsewhere, and so are its parameters, their defaults and which ones are
required. An instance of an `External` may set any parameter. Its type follows
from its value, and the simulator checks it.

| Rule | |
| --- | --- |
| A-1 | An instance of a `Subckt` only sets parameters the `Subckt` declares. |
| A-2 | An instance sets each parameter at most once. |
| A-3 | Values match the declared type (instance values and defaults alike). |
| A-4 | An expression in an instance value refers only to number parameters of the containing cell. |
| A-5 | An expression in a default refers only to number parameters declared earlier in the same cell. |

### 7.2 Expressions

An `Expression` holds a tree. Text is only how JSON and the HDL spell it. Nodes:
`Number(value)`, `ParamRef(name)`, `Neg(operand)` (negation),
`Binary(op, left, right)` with `op` one of `+ - * /`, and `Call(function, args)`.
Power is the function `pow(x, y)`, not an operator. The text grammar:

```
expr    := term (("+" | "-") term)*
term    := unary (("*" | "/") unary)*
unary   := ("+" | "-") unary | atom
atom    := NUMBER | NAME | NAME "(" expr ("," expr)* ")" | "(" expr ")"
```

The parser drops a unary `+` (`+w` is `w`). Functions: `abs`, `sqrt`, `exp`,
`ln`, `log10` (one argument), `min`, `max`, `pow` (two). Writers render as each
dialect needs.

### 7.3 Numbers

Numbers are exact, finite `Decimal`s. As text:
`[+-]?(digits[.digits]|.digits)([eE][+-]?digits)?`, without scale factors.

Canonical text is engineering notation. The mantissa uses the fewest exact
digits with 1 <= |mantissa| < 1000, and the exponent is a multiple of 3, written
without padding. A number whose exponent is 0 is written plainly, and zero is
`0`. Examples: `120`, `4.7e3`, `750e-3`, `1e-3`, `1.5e-6`, `150e-15`, `2.4e9`.
Equal numbers always print the same.

## 8. Metadata

Cells and instances, the nodes of the hierarchy, carry a `meta` field. `Meta`
holds annotations that never affect meaning: `==`, hashing, validation and
every writer output other than comments ignore it. Anything that changes output
is circuit information and is a regular field, never part of `Meta`.

| Field | |
| --- | --- |
| `origin` | Where the node was created, as a human-readable string (`"tb/tb_inv.py:30"`, `"ip.scs:1234"`). |

New annotations are added as new optional fields of `Meta`.

## 9. Field rules

| Rule | |
| --- | --- |
| F-1 | Every field has its declared type: model classes, enum members, `int` (not `bool`), `str`, `Decimal`, tuples (not lists). Required fields are set. |
| F-2 | Every identifier matches the grammar of section 3. |
| F-3 | `Range.msb` and `Range.lsb` are `>= 0`, `NoConnect.width >= 1`, and `Number.value >= 0` (a negative number is a `Neg` of its magnitude). |
| F-4 | A `Connection` has at least one piece. |
| F-5 | Numbers are finite. |
| F-6 | `Binary.op` is one of `+ - * /`, and `Call.function` is from section 7.2 with the right number of arguments. |
| F-7 | A `Netlist` has at least one cell. |

