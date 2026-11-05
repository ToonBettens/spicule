# spicule.ir v1: specification

The model is the Python dataclasses in `src/spicule/ir/model.py`. This document
describes the model and numbers every rule a valid `Netlist` follows. The
reasoning behind it, and the alternatives that were weighed, are in
`ir-decisions.md`.

## 0. Scope

The IR is the circuit part of a SPICE deck in structured, dialect-neutral form:
subcircuits, instances, nets and parameters. The HDL and other producers make
it, and writers and tools read it.

## 1. Conventions

1. **Required and absent.** A required field is a required constructor argument.
   An optional field is `None` when absent. Sequences are tuples (empty has
   meaning). A field holding one of several kinds is a union.
2. **Immutable values.** Every class is a frozen, slotted, keyword-only
   dataclass. Enums are plain `Enum`s with lowercase values.
3. **Order is part of the value.** Tuples compare in order, so two netlists that
   list the same instances in a different order are different values. Producers
   emit in a deterministic order and every tool preserves it. Port order is also
   pin order, and piece order is also bit order. An order-insensitive comparison
   would be a helper of its own.
4. **Equality is circuit equality**, with these refinements:
   - `meta` fields are ignored.
   - numbers are `Decimal` and compare numerically, wherever they appear in an
     expression (`1.5e-6 == 0.0000015`).
   - connections have one canonical form, so equal wiring compares equal.
   - expressions are trees and compare structurally (`w*2 == w * 2 == (w)*2`,
     `2.0*w == 2*w`).
5. **Versioning.** JSON carries `"format": "spicule.ir/1"`. Within version 1
   only additive changes. Readers reject unknown versions.
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
    params:  ParamDecl(name, default)                     Subckt only, default: Expression
    signals: Signal(name, range?)                         internal nets only
Instance(name, cell, connections, params, meta)           cell: the instantiated cell's name
    connections: Connection(port, pieces)
    pieces:      SignalRef(signal, range?) | NoConnect(width)
    params:      ParamValue(name, value)
Range(msb, lsb)
Meta(origin?)                                             annotations, never affect meaning
Value = Expression(root) | str                            a str only on External instances
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

Reserved keywords or case-insensitivity are checks consumers are responsible
for.

## 4. Cells and references

A netlist holds one or more top cells and every cell they use, each once, leaves
first. Every instantiated cell is in it: `Subckt`s defined here, and PDK
devices, foreign subcircuits and built-ins as `External` cells.

A cell's name is its identity and is final: an instance names its cell.

| Rule | |
| --- | --- |
| D-1 | Every `Instance.cell` is the name of a cell in the netlist. |
| D-2 | Define before use: an instantiated cell comes earlier in `Netlist.cells` than the cell containing the instance. |

## 5. External cells

An `External` is the interface of a cell defined elsewhere: its name and ports
in pin order, without contents. It stands for a PDK device, an IP block or an
element of the simulator. Its parameters are not declared (section 7.1), and the
files that define it are included by a simulation (`sim-spec.md`).

To call it, a writer must know what the name refers to, because the first letter
of a SPICE instance name tells whether `nch` is a subcircuit (`X`) or a
transistor model (`M`). `element` records this:

| `element` | The name refers to | Instance line |
| --- | --- | --- |
| `subckt` | a subcircuit defined in an included file | `X1 a b c name` |
| `mos` | a transistor model in an included file | `M1 d g s b name w=...` |
| `diode`, `bipolar` | a diode or bipolar model | `D1 ...`, `Q1 ...` |
| `resistor`, `capacitor`, `inductor` | a resistor, capacitor or inductor model | `R1 a b name ...` (C, L) |

**Built-ins** are elements the simulator provides itself, without any included
file, such as an ideal resistor or a voltage source. They have `element`
`builtin`, and the name is the simulator's own name for the element, with the
simulator's own parameters. spicule declares each dialect's built-ins for the
HDL (`spicule.hdl.builtins`), and each writer rejects a built-in name it doesn't
know.

## 6. Nets and connections

### 6.1 Signals and buses

A `Signal` without `range` is a scalar net. With a range (even `<0:0>`) it is a
bus. `Range(msb, lsb)` is defined as: `msb` is the left index, `lsb` the right
one, either may be larger, both `>= 0`. A range expands left to right: `<3:0>`
is bits 3, 2, 1, 0 and `<0:3>` is 0, 1, 2, 3. A bus port contributes its bits to
the pin list in expansion order.

Writers spell bus bits per dialect (`d<3>`, `d\<3\>`, ...).

### 6.2 Connections

An instance's `Connection` gives, for one port of the instantiated cell, a list
of pieces in expansion order. The pieces' bits, concatenated, meet the port's
bits first to first. A piece is:

- `SignalRef(signal, range?)`: bits of a port or internal signal of the
  containing `Subckt`. No range: the whole signal (scalar or whole bus). With a
  range: those bits, in either direction (`d<0:3>` of a `d<3:0>` bus). A single
  bit is written `<5:5>`.
- `NoConnect(width)`: `width` bits deliberately left open. Writers give each bit
  a unique net.

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
  `SignalRef`, and a run that is exactly the whole bus in its declared direction
  is written without range.
- A bit of a scalar signal is a piece on its own.
- Consecutive open bits form one `NoConnect`.

| Rule | |
| --- | --- |
| C-5 | Pieces are in canonical form. |

`canonical_pieces()` implements it for one connection, and every producer calls
it. `canonicalize()` does it for a whole netlist. Example: with `d<7:0>`
declared, bits `d<3> d<2> d<5> d<6> NC NC` are the pieces `d<3:2>`, `d<5:6>`,
`NoConnect(2)`.

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

A `Subckt` declares `ParamDecl(name, default)`. Every parameter has a default,
so an instance never has to set one. Subckt parameters are numbers: the default
and every value set on an instance are `Expression`s. A plain number is the
smallest expression, `Expression(Number(...))`. An instance sets
`ParamValue(name, value)`. Only on an instance of an `External` may a value also
be a `str`, for text parameters of devices and built-ins (`type=dc`,
`file="in.pwl"`). Multiplicity `m` is an ordinary parameter: a subckt that
accepts it declares it.

An `External` declares no parameters. They are open: the cell is defined
elsewhere, and so are its parameters, their defaults and which ones are
required. An instance of an `External` may set any parameter. Its type follows
from its value, and the simulator checks it.

| Rule | |
| --- | --- |
| A-1 | An instance of a `Subckt` only sets parameters the `Subckt` declares. |
| A-2 | An instance sets each parameter at most once. |
| A-3 | A value set on an instance of a `Subckt` is an `Expression`. |
| A-4 | An expression in an instance value refers only to parameters of the containing cell. |
| A-5 | An expression in a default refers only to parameters declared earlier in the same cell. |

### 7.2 Expressions

An `Expression` holds a tree. Text is only how writers print it and readers read
it. Nodes: `Number(value)`, `ParamRef(name)`, `Neg(operand)` (negation),
`Binary(op, left, right)` with `op` one of `+ - * /`, and `Call(function,
args)`. Power is the function `pow(x, y)`, not an operator. The text grammar:

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
holds annotations that never affect meaning: `==`, hashing, validation and every
writer output other than comments ignore it. Anything that changes output is
circuit information and is a regular field, never part of `Meta`.

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

## 10. The netlist file

`spicule.dialects.jsonio` writes a valid netlist as JSON text with
`write(netlist)`, and `read(text)` reads it back: a valid netlist, equal to the
one written, with its `meta` intact. The file is for looking at the IR,
comparing designs and keeping them.

The top level is `{"format": "spicule.ir/1", "cells": [...]}`: the format and
its version, then the cells. Below it, the file follows the model field for
field:

- Field names are the model's. Every field is always written: an absent optional
  is `null`, an empty sequence `[]`.
- Sequences are lists, in the model's order.
- Enums are their values: `"element": "mos"`.
- A `kind` says which one it is wherever a value can be one of several:

  | Value | `kind` | Other fields |
  | --- | --- | --- |
  | Cell | `subckt`, `external` | the cell's fields |
  | Piece | `signal_ref`, `no_connect` | the piece's fields |
  | Parameter value | `expression`, `text` | `text`: the expression's text, or the text itself |

An expression is its text as `format_expression` writes it. Numbers are
therefore exact, and `parse_expression` gives back the same tree.

```json
{
  "name": "mn",
  "cell": "nch",
  "connections": [
    {"port": "d", "pieces": [
      {"kind": "signal_ref", "signal": "q", "range": {"msb": 3, "lsb": 2}},
      {"kind": "no_connect", "width": 2}
    ]}
  ],
  "params": [
    {"name": "nfin", "value": {"kind": "expression", "text": "2*nfin"}},
    {"name": "flavor", "value": {"kind": "text", "text": "lvt"}}
  ],
  "meta": {"origin": "design.py:12"}
}
```

Text that isn't JSON, another format or version, a missing or unknown field or
an unknown `kind` raises `FormatError`, naming where in the file. A file with
the right shape whose netlist breaks a rule raises `ValidationError`.

A simulation has a file of its own, with a netlist in it (`sim-spec.md`, section
6).
