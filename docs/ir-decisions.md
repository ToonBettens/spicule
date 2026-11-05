# spicule.ir decision record

Why `spicule.ir` looks the way `ir-spec.md` describes it. Each fundamental
choice is a numbered record with its alternatives scored against the same
criteria. The overview below lists them, and the smaller reasons are at the end.
Alternatives are kept as they were weighed, so they can name things that no
longer exist.

## Goal and principles

**Goal.** The IR holds everything the circuit part of a SPICE deck needs
(subcircuits, instances, nets, parameters) in the structure it *should* have.
Not the simulator's flat internal form: hierarchy, parameter expressions and
names must survive. Not the simulation setup either: the same circuit goes to
LVS.

**Lens.** The IR models circuit concepts properly. Dialects are only how we
spell them. A legacy limitation of SPICE or of a tool (no buses, case folding,
line order) is handled by the writer for that tool, never by bending the IR.

**What belongs in the IR**, for every concept:

1. every consumer would compute it the same way: the producer resolves it once
   (generators, loops, build parameters and name choice stay in the HDL),
2. a consumer needs it and can't derive it: it is in the IR,
3. a consumer can derive it cheaply: it is left out,
4. only one dialect or tool has it: writer option, not IR.

**What is left out, and why:**

| Concept | Why not | Where instead |
| --- | --- | --- |
| Analyses, options, saves, includes, `.model` cards, `.ic`/`.nodeset`, temperature, corners, raw lines | Setup of one simulation, not the circuit (R-21) | `spicule.sim` |
| Reference node (ground, `0`) | Which net is the reference is a fact about a simulation (R-12) | `Simulation.ground` names a net of the top cell |
| Global nets | Hidden wiring. Ports say the same thing explicitly (R-12) | Ports. Readers turn imported globals into ports |
| Inherited connections, hierarchical net references | Connectivity that depends on where a cell is used | Ports |
| Libraries, namespaces | Names are unique and final (R-2) | HDL naming (generator name formats) |
| Top cell | Derivable: the cells nobody instantiates | `Simulation.top` |
| Purpose (layout / simulation) | The same netlist goes to every writer (R-7) | Which writer is called |
| Port direction | No consumer. Analog pins are mostly bidirectional (R-13) | Optional field later (additive) |
| Descriptions, generic metadata | No consumer today | Typed optional fields when one appears |

## Criteria (most important first)

1. **C1 Wrong states can't be represented.**
2. **C2 One representation per circuit.**
3. **C3 Fewest rules.**
4. **C4 Matches how designers think.**
5. **C5 Simple for writers and readers.**

Scores: ++ strong, + good, 0 neutral, - weak, -- poor. **Veto** marks a
practical blocker outside the criteria (scaling, editing, correctness of
output).

## Overview

| Record | Question | Choice |
| --- | --- | --- |
| R-1 | Container and references | Flat list of cells, instances refer by unique name |
| R-1b | Name of the container | `Netlist` |
| R-2 | Cell identity | Unique final names, settled by the producer |
| R-3 | Cell order | Leaves first, required |
| R-4 | Ports and signals | `ports` in pin order, internal signals apart |
| R-4b | Internal signals | Declared |
| R-5 | Kinds of cell | Two flat classes, `Subckt` and `External` |
| R-6 | How an external cell is called | One `element`, no built-in list in the IR |
| R-7 | Purpose (layout / simulation) | None |
| R-8 | Buses | `Range(msb, lsb)`, either direction |
| R-8b | A bus partly port, partly internal | No |
| R-9 | Connections | Pieces, in one canonical form |
| R-10 | Connection by name or position | By port name |
| R-11 | Deliberately open bits | `NoConnect(width)` |
| R-12 | Ground and global nets | Neither, a simulation names the reference net |
| R-13 | Port direction | None |
| R-14 | Parameter declaration and value | Separate classes |
| R-14b | Parameters of external cells | Open |
| R-14c | Defaults and required parameters | Subckt parameters always have a default, externals declare none |
| R-15 | Parameter types | Number or expression, and string |
| R-15b | Text parameters on subckts | No, numbers only |
| R-16 | Multiplicity `m` | An ordinary declared parameter |
| R-17 | Numbers | Exact `Decimal`, no scale factors |
| R-17b | Plain numbers and expressions | Always an `Expression` |
| R-18 | Expressions | A tree, text only in JSON and the HDL |
| R-19 | Equality and order | Order is part of the value |
| R-20 | Names | Identifier grammar, case-sensitive |
| R-21 | Scope of the IR | The circuit only |
| R-22 | Source locations | A typed `meta` on cells and instances |

## Netlist and cells

### R-1 Container and references

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Libraries containing cells, instances refer by `CellRef(library, cell)` (hdlkit) | - | + | - | 0 | 0 | Two-level lookup, extra ordering rule for libraries |
| b. Object graph: an instance holds the cell object | ++ | + | ++ | + | - | **Veto**: shared cells make `==`/`hash` blow up exponentially. Changing one cell means rebuilding every ancestor |
| c. Flat list of cells, instances refer by unique name | + | + | + | + | ++ | Same shape as every netlist format |
| d. vlsir: package with modules + external modules, local/external references | 0 | + | - | 0 | 0 | Two kinds of reference for one concept |

**Choice: c.** b scores best on C1/C3 but is vetoed.

### R-1b Name of the container

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Package` (hdlkit, vlsir) | 0 | 0 | 0 | - | 0 | Confusing next to Python packages |
| b. `Design` | 0 | 0 | 0 | - | 0 | Suggests one circuit with a top |
| c. `Netlist` | 0 | 0 | 0 | + | + | Exactly what a netlist file is: subcircuits calling each other by name. Free since R-5 |
| d. `Circuit` | 0 | 0 | 0 | 0 | 0 | Suggests a single circuit |

**Choice: c.** Naming only. The criteria hardly separate the options.

### R-2 Cell identity and naming

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Library + cell name, writer resolves netlist-name clashes | 0 | 0 | - | + | - | Every writer needs clash handling |
| b. Unique final names in the IR. The HDL settles names (strict, generator name formats) | + | ++ | + | + | ++ | Writers print names as they are |
| c. Object identity, names assigned at write time | ++ | - | 0 | 0 | - | Names unstable across runs |

**Choice: b.** A clash with a name inside foreign IP is settled by naming the
cell differently in the HDL.

### R-3 Cell order in the netlist

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Leaves first, required (define before use) | + | 0 | + | 0 | ++ | One rule, which also excludes cycles. Writers emit in one pass |
| b. Any order, cycles forbidden | + | 0 | + | 0 | + | One rule (no cycles). Every writer sorts first |

C1 to C4 tie (both one rule, both allow several valid orders of the same cells).
C5 decides: leaves first saves every consumer a sort, and the HDL produces that
order anyway.

**Choice: a.**

### R-4 Ports and signals

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. One signal list per cell, `ports` are names into it (vlsir, hdl21) | - | + | - | 0 | + | Needs "ports name existing signals, no duplicates" and "externals have only port signals" |
| b. `Cell.ports: Signal...` in pin order, internal signals in `Netlist.signals` (hdlkit) | ++ | + | + | + | + | One rule: port and signal names unique together. An external cell can't have internals |
| c. One list of signals with a port flag and pin position | - | - | - | - | 0 | Pin order as numbers invites gaps and duplicates |

**Choice: b.** With R-5 the internal signals live on `Subckt`. Wins C1, C3 and
C4. The only cost is that "all nets of a cell" is `ports + signals` instead of
one list.

### R-4b Internal signals declared or implicit

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Declared in `Subckt.signals`, with ranges | + | - | 0 | + | + | Bus width and direction stated. Typos caught. An unused declared signal is a second spelling of the same circuit |
| b. Implicit: nets are the names connections mention (SPICE) | - | + | - | 0 | - | Whole-bus connections can't give a width. `<3:0>` vs `<0:3>` must be guessed. A typo silently makes a new net |

**Choice: a.** An unused internal signal is a warning, not an error. Explicit
declaration follows from wanting bus connections, and it also catches typos.

### R-5 Kinds of cell

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. One `Cell` with `body: Netlist \| External` (hdlkit) | ++ | ++ | ++ | + | 0 | Extra nesting level: `cell.body.instances` |
| b. Two flat classes: `Subckt(name, ports, params, signals, instances)` and `External(name, ports, params, element)`. `Netlist.cells: Subckt \| External` | ++ | ++ | ++ | ++ | + | Same safety without nesting. `name, ports, params` repeated in both |
| c. One flat `Cell` with optional `element`, `signals`, `instances` | - | 0 | - | + | + | A device with instances can be built. Needs a rule |

**Choice: b.** It keeps a's safety and drops the nesting.

### R-6 How an external cell is called

Every `External` cell names something defined outside the netlist. `element`
says where that name lives.

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `kind` (primitive/device/subckt) + `spice_type` (hdlkit) | -- | + | -- | 0 | 0 | Invalid combinations need two rules |
| b. One `element`: `subckt` (name in an included netlist), `mos`/`diode`/`bipolar`/`resistor`/`capacitor`/`inductor` (name is a PDK model), `builtin` (name is in the simulator's own vocabulary). No built-in list in the spec | ++ | ++ | ++ | + | + | Built-ins are declared like PDK devices, per dialect. Each writer rejects built-ins it doesn't know |
| c. One `element` with a member per built-in (`vdc`, `ideal_resistor`, ...) | ++ | ++ | + | 0 | + | The IR fixes a built-in list that every simulator must support. Awkward names next to the model elements |

**Choice: b.** The IR must fit a simulator with barely any built-ins, so the IR
knows no built-ins. `builtin` plus a name is no more magic than `mos` plus
`nch`.

Why keep `element` although Spectre ignores it: a Spectre instance names its
master and Spectre resolves it itself (primitive, model or subckt), so the
element letter means nothing there. CDL makes the writer choose the element
letter, and `M1 ... nch` versus `X1 ... nch` are different statements.
Which one is right depends on the PDK's model files, which are not in the IR.
Needed by a consumer and not derivable, so it stays (inclusion rule 2). The
Spectre writer still uses `builtin` to know when to apply its built-in table.

Built-ins per simulator, no spicule standard set: a portable set would make
spicule own the meaning of every source and translate it per simulator (pulse
parameter order and defaults, sine phase units, AC conventions differ), with
only the common denominator available. Instead each dialect ships its own
built-ins under the simulator's names and parameters, and its writer rejects
unknown names. Cost: a testbench with built-ins is tied to one simulator, as its
setup already is. Designs without built-ins stay portable. A portable helper in
the HDL can be added later without changing the IR.

The list follows one rule: one value per kind of netlist line, so `subckt` (X),
`builtin`, and one per SPICE element letter that takes a model name. More such
letters (`jfet` J, switches S/W, lossy lines O) can be added as new members
without breaking anything.

One declaration serves Spectre and CDL. Lines from generated netlists:

```
CDL:      MM0 BIT BITb VDD VDD pch l=20.0n nfin=2 nf=1
Spectre:  pu (BIT BITb VDD VDD) pch l=20n nfin=2 nf=1
```

The device name is the same in both (`pch`), CDL calls it with the element
letter `M` (so `element` is `mos`, which Spectre ignores), and the parameters
differ only in which ones each tool's netlister chose to print. One `External`
declaration with all parameters serves both writers, and each writes the
parameters an instance sets.

### R-7 Purpose (layout / simulation)

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Netlist.purpose` with rules (no ground or built-ins in layout cells) | + | + | - | + | + | Two rules, information derivable |
| b. None: the same netlist goes to every writer | + | + | ++ | 0 | + | |

**Choice: b.** CDL writes what it can spell. An ideal resistor, capacitor or
inductor in an LVS netlist shows up as a mismatch in Calibre, and a `vsource` is
refused because CDL has no spelling for it.

## Nets and connections

### R-8 Buses

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Range(msb, lsb)`, either direction | + | + | 0 | ++ | + | Keeps index offset and pin order (`d<3:0>` vs `d<0:3>`) |
| b. Width only (vlsir) | + | + | + | - | - | Loses offset and order: vlsir's open ordering FIXME |
| c. No buses, net names like `d<3>` | - | 0 | + | - | - | Every tool reparses names (the SPICE limitation) |

**Choice: a.**

### R-8b A bus that is partly port, partly internal

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. No: a name is one net, port or internal, scalar or bus | + | + | + | 0 | + | Split halves get different names (`d`, `d_hi`) |
| b. Yes, per bit (Virtuoso allows pin `d<3:0>` plus wire `d<7:4>`) | - | - | -- | + | - | Uniqueness and range rules per bit instead of per name |

**Choice: a.** A future netlist reader meeting a split bus renames one half.

### R-9 Connections

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Flat bit list per port | ++ | ++ | ++ | -- | + | Loses "bus to port" intent |
| b. Pieces (slices, no-connects), canonical form required | + | ++ | - | + | + | Non-canonical splits are invalid (extra rule) |
| c. Pieces in any split, equality by expanded bits, producers write canonical form | + | 0 | + | + | 0 | Structurally many spellings, semantically one. Custom `==`/hash expands every bit |
| d. vlsir: signal / slice / nested concat | - | - | - | + | - | Nesting, three kinds for one idea |

**Choice: b.** It beats c on C2 (one representation, identical JSON, plain `==`
without expanding bits) and loses only one rule. C's argument (readers failing
on a split) disappears because every producer calls `canonicalize()`. Note:
strictly by criteria order a wins (best on C1-C3). It is overridden on the lens
(bus-to-port intent is a real concept, R-8), not on the criteria.

The slice piece is named `SignalRef`, not `Slice`. It also refers to a scalar
signal or a whole bus, which are not slices, and it pairs with `ParamRef`:
`Signal` declares a net and `SignalRef` uses it, as `ParamDecl` and `ParamRef`
do for parameters.

### R-10 Connection by port name or position

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. By port name | + | 0 | 0 | + | + | One rule: every port exactly once |
| b. By position (like a SPICE line) | + | + | + | - | 0 | Silent shifts when a port is added. Poor error messages |

**Choice: a.** b scores slightly better on C2/C3 but fails on robustness, and named
connections give errors like "port `d` of `inv`".

### R-11 Deliberately open bits

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `NoConnect(width)` piece | + | + | 0 | + | + | Intent visible. Enables a floating-net check |
| b. Producer makes a dummy net | 0 | - | + | - | + | Intent lost. Dummy names vary |

**Choice: a.**

### R-12 Ground and global nets

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Special `Ground` piece (hdlkit) | 0 | + | - | 0 | + | Needs "ground only in simulation cells" |
| b. Declared globals, ground = global `0` | 0 | 0 | - | 0 | 0 | Hidden wiring. Extra declaration and rules |
| c. Neither: everything through ports. A simulation names the reference net | + | + | ++ | + | + | Testbenches wire `gnd` explicitly |

**Choice: c.**

### R-13 Port direction

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. None | + | + | ++ | 0 | + | Analog pins are mostly bidirectional |
| b. in / out / inout | 0 | + | - | + | 0 | No consumer. CDL `*.PININFO` optional |

**Choice: a.** Easy to add later: an optional `direction` on port signals is an
additive change within version 1 (absent = unknown). Making it required later
would be version 2.

## Values

### R-14 Parameters: declaration and value

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Separate `ParamDecl(name, type, default?)` and `ParamValue(name, value)` | ++ | + | + | + | + | "Required" is expressible |
| b. One `Param(name, value)` for both (vlsir) | - | 0 | + | 0 | 0 | Can't say "required, no default" |

**Choice: a.** R-14c and R-15b later took out the required case and the `type`,
and the two classes stayed.

### R-14b Parameters of external cells

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Closed, like `Subckt`: only declared parameters, no default means required | + | + | 0 | - | -- | Every simulator and PDK parameter has to be declared, with defaults we don't own |
| b. Every parameter must have a default | - | + | + | - | - | Hides a forgotten parameter in our own cells. Copies foreign defaults |
| c. Open: any parameter may be set, none is required, declared ones are type-checked | 0 | + | + | + | ++ | A typo on a device is caught by the simulator or LVS instead of the validator |

**Choice: c, for `External` only.** The authority on an external cell's
parameters is the PDK or the simulator, which reject unknown parameters
themselves. `Subckt` parameters stay closed (A-1): there the cell is ours, and a
misspelt parameter is our bug. R-14c goes further: externals declare no
parameters at all.

### R-14c Parameter declarations, defaults and required parameters

R-14b makes every parameter of an external cell optional, while PDK models do
have required parameters (`nfin`). The simulator refuses an instance without
them, but the model files that say so, and their defaults, are often protected
and can't be read. A default declared on an `External` was type-checked and then
used nowhere. Required subckt parameters, in turn, are rare, and CDL can't write
them.

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `ParamDecl` gets `required: bool`. A `Subckt` param is required exactly when it has no default. An `External` param has no default | 0 | + | - | + | + | Two new rules. A `Subckt` decl with `required=False` and no default can be built |
| b. `External.required: tuple[str, ...]`, no defaults on externals | - | 0 | - | 0 | 0 | A parameter's facts in two places |
| c. Externals closed like a `Subckt`: no default means required, every default copied | + | + | ++ | - | + | **Veto**: the defaults are the PDK's, and often unreadable. A copy goes stale silently |
| d. A separate `ExternalParam(name, type, required)` for externals, `ParamDecl(name, type, default?)` for subckts | ++ | ++ | + | + | + | One more class. Required parameters stay in both cells |
| e. One `ParamDecl`, no default means required in both cells. No defaults on externals: a house default is copied onto instances by the producer | + | + | + | 0 | + | The same HDL spelling means required on a subckt and open on an external unless declared |
| f. Every `Subckt` parameter has a default, nothing is required. An `External` declares no parameters at all | ++ | ++ | ++ | + | ++ | Loses Spectre's required subckt parameters and an early error for a forgotten PDK-required parameter |

**Choice: f.** Two simple statements replace three rules. A subckt parameter
always has a value we own, so no instance has to set it, and every subckt can be
written in every dialect (CDL has no required parameters). An external cell's
parameters are owned by the PDK or the simulator, including their defaults and
which ones are required, so the IR declares none. It only records what an
instance sets, whose type follows from the value. The simulator reports a
missing required parameter by instance name.

A default we want for an external cell ("our `nch` uses `l=16e-9`") is a choice
about how we use the cell, not a fact about the cell. The producer writes it on
each instance, so the value is explicit in the IR and in the netlist.

Considered and left out: closed externals that refuse unknown names. Nothing
needs them yet. The flag can be added later without breaking anything.

### R-15 Parameter types

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Number (or expression) and string | + | + | + | + | + | What simulators take |
| b. Also bool, int, enum (vlsir) | 0 | - | - | + | - | `1` vs `1.0` vs `true` spell the same value |

**Choice: a.**

### R-15b Text parameters on subckts

R-14c gives every `Subckt` parameter a default, so a parameter's type could
simply be read from its default. But what would a text parameter on a subckt be
for? Inside the subckt it can't be used: parameters are only used through
`ParamRef` in expressions, which are numbers. Passing it on to a device would
need a text reference, a new kind of value, and Spectre's subckt parameters are
numeric. Nor does a simulator vary text: `sweep` and Monte Carlo step numbers,
and corners switch model sections in the setup.

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. A `type` field next to the default (number or string) | - | 0 | - | 0 | 0 | Type and default can disagree, and a text parameter can't be used |
| b. The type is the default's type | + | + | + | 0 | 0 | Nothing to disagree, but text parameters still can't be used |
| c. Subckt parameters are numbers. Text only as a value on an `External` instance | ++ | ++ | ++ | + | + | A text choice that varies (a flavour, `"lvt"`) is a build parameter |

**Choice: c.** `ParamDecl(name, default)` with an `Expression` default, and no
parameter types at all. A text value is only written on instances of external
cells (`type=dc`, `file="in.pwl"`, `probe=vsense`). A text choice that differs
between uses is fixed per design, so the generator takes it as a build parameter
and writes the literal text on the device. That works in every dialect and shows
the real value in the netlist.

### R-16 Multiplicity `m`

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Implicit name, settable without declaring (hdlkit) | - | + | - | 0 | 0 | Hidden exception |
| b. Dedicated field `Instance.m` | + | + | + | 0 | + | |
| c. Ordinary declared parameter (vlsir, hdl21) | + | + | ++ | + | 0 | Spectre's built-in subckt `m` becomes a writer detail |

**Choice: c.**

### R-17 Numbers

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Exact `Decimal`, no scale factors | + | ++ | + | + | + | `1.5e-6 == 0.0000015`. No rounding in generators |
| b. Float | 0 | - | + | + | + | `0.1 + 0.2 != 0.3` reaches netlists |
| c. Prefixed (vlsir) | - | -- | - | + | - | `1m` means different things per tool |

**Choice: a.**

### R-17b Plain numbers and expressions

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. A number value is a `Decimal` or an `Expression` | - | -- | 0 | + | 0 | `w = 2` can be `Decimal(2)` or `Expression(Number(2))`, which compare unequal |
| b. As a, plus a rule that an expression is never a bare number | + | ++ | - | + | 0 | Every producer must unwrap |
| c. A number value is always an `Expression`. A plain number is `Expression(Number(...))` | ++ | ++ | ++ | 0 | + | One representation and one writer path. Verbose by hand (a helper covers it) |
| d. Separate parameter types for literal numbers and expressions | 0 | 0 | -- | 0 | - | No simulator distinguishes them |

**Choice: c.** `Decimal` stays as the storage of every number, inside `Number`
leaves, so `0.075` and `7.5e-2` still compare equal.

### R-18 Expressions

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Text (hdlkit, vlsir) | - | -- | 0 | + | - | `w*2 != w * 2`. Every writer parses |
| b. Text with one canonical spelling | 0 | + | - | 0 | - | Every producer must emit exactly that spelling |
| c. Tree, text only in JSON and the HDL | ++ | + | + | + | ++ | |

**Choice: c.** Text would need the same parser in the validator and every
writer.

## Cross-cutting

### R-19 Equality and order

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Order part of the value (tuples), producers emit deterministic order | 0 | 0 | ++ | 0 | ++ | Same circuit in two orders compares unequal |
| b. Order-free collections (mappings / frozensets) | + | ++ | 0 | 0 | - | Writers need a sort rule anyway for stable output |

**Choice: a.** Port and piece order always carry meaning. Comparing netlists
from two different producers (e.g. HDL vs a netlist reader) would use an
order-insensitive helper.

### R-20 Names

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Identifier grammar, case-sensitive. The CDL writer rejects case-only clashes | + | + | + | + | + | |
| b. Identifier grammar, unique ignoring case (hdlkit) | + | + | 0 | 0 | + | A Calibre limitation in the IR |
| c. Any string, writers escape | - | 0 | + | + | -- | Escaping rules in every writer |

**Choice: a.**

### R-21 Scope of the IR

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Circuit only. Simulation setup is a separate structure | + | + | + | + | + | Same circuit goes to LVS untouched |
| b. Circuit plus analyses, includes, options | 0 | 0 | - | 0 | 0 | LVS writers must ignore half the IR |
| c. Simulator-internal flat form | - | + | + | -- | - | Loses hierarchy, expressions and names |

**Choice: a.**

### R-22 Source locations

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `source` fields on cells and instances, ignored by `==` (hdlkit) | + | 0 | - | 0 | + | Ad hoc exception: non-circuit fields, special equality, own rules and path logic |
| b. Separate origin table passed alongside the netlist | + | + | + | 0 | - | Plumbing everywhere. Goes stale when a transform renames or restructures |
| d. Typed `meta` field on cells and instances, one documented rule | + | + | 0 | 0 | + | One principled exception. Risk of becoming a dumping ground |
| e. Origin table in a slot on `Netlist` | + | 0 | 0 | 0 | + | b's staleness plus a's exception |
| f. Nothing in the IR. Each producer maps errors back to its own input | + | ++ | ++ | 0 | + | `elaborate()` keeps its own name-to-line map and annotates validation errors. Writer errors name unique cells and instances |
| g. Flat `origin: str` on cells and instances, one rule | + | + | + | + | + | Each future annotation adds another exception to list |
| h. `meta: Meta` on cells and instances. `Meta` is typed (starts with `origin: str`). One structural rule: everything is compared except `meta` | + | + | + | + | ++ | Like MLIR locations / LLVM metadata. New annotations go inside `Meta` without touching any rule |

**Choice: h.** Source lines should be available in written netlists. The two
objections to a metadata bag are answered by: (1) `origin` is an uninterpreted,
producer-written string, so no definition of "location" is needed and new
producers can't break it, and (2) only the nodes of the hierarchy (cells and
instances) have `meta`, because they are what a hierarchical path consists of
and what becomes a statement in a netlist. `Meta` is a typed class, not a
dictionary. Anything that changes output other than comments is circuit
information and never goes in `Meta`. A separate table (b, e) was rejected
because it goes stale under transforms.

## Smaller choices

The reasons behind individual rules, by section of `ir-spec.md`:

| Spec | Choice | Why |
| --- | --- | --- |
| 1.1 | Required fields have no "unspecified" value | vlsir's proto3 defaults silently meant INPUT, SUBCKT and 1e-24 |
| 1.2 | Frozen dataclasses. Enums never equal strings | Values can be shared, hashed and compared safely. A bare string in place of an enum member is caught |
| 3 | Identifier alphabet `[A-Za-z_][A-Za-z0-9_]*` | A deliberate portable alphabet, legal unescaped in Spectre, CDL and GDS, so no writer needs escaping rules for names |
| 4, D-2 | Define before use | Excludes cycles in the same rule, and writers emit in one pass (R-3) |
| 5 | No built-in list in the IR. Built-ins per dialect | The IR must fit any simulator, including one with barely any built-ins. No translation of source semantics between simulators (R-6) |
| 6.1 | Ranges, not widths | Index offset and order both matter (pin order, layout pin names `d<3>`). A width loses them (R-8) |
| 6.2 | `NoConnect` | "Open on purpose" is design intent. A floating-net check needs it (R-11) |
| 8 | `meta` only on cells and instances. `origin` an uninterpreted string | The hierarchy's nodes are what paths and netlist statements consist of. Producers define their own notion of location (R-22) |
| C-1 | Every port connected exactly once | A missing port is an error, never an implicit open |
| 6.3 | Canonical form required | Plain dataclass equality, one JSON form per circuit, no bit expansion on every comparison (R-9) |
| 6.4 | Floating nets are warnings | A spare net is harmless and handy while editing |
| A-4 | Instance expressions only see the containing cell's parameters | No silent inheritance from enclosing scopes (Spectre would allow it) |
| A-5 | Defaults only refer to earlier parameters | Evaluation order is obvious. No cycles |
| 7.1 | No bool or int parameter types | Simulators take numbers and strings. A flag is 0/1 (R-15). Subckt parameters are numbers only (R-15b) |
| 7.2 | Unary `+` dropped | Otherwise `+w` and `w` would be different trees |
| 7.2 | Functions `abs sqrt exp ln log10 min max pow` | Only functions every dialect has with the same meaning. `log` left out because tools disagree on its base |
| 7.2 | Power is the function `pow`, not an operator `^` | One spelling everywhere (tree, text, every writer). No associativity or precedence rules for `^`, and Spectre's `^` doesn't mean power anyway |
| F-3 | `Number` values are never negative. Negation is always `Neg` | Otherwise `-1` has two trees, `Number(-1)` and `Neg(Number(1))` (C2). The parser only produces the second |
| 7.3 | No scale factors | Calibre reads `M` as milli, other tools as mega |
| 7.3 | Engineering notation (exponent a multiple of 3, unpadded, plain when the exponent is 0) | Every exponent maps onto a familiar prefix (`e-6` is u, `e3` is k). Exact, and equal numbers still always print the same |
| 10 | The JSON module is `jsonio`, not `json` | It would shadow the standard library in user code |
