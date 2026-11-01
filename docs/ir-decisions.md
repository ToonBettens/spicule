# spicule.ir decision record

Why `spicule.ir` looks the way `ir-spec.md` describes it: the goal and principles, every fundamental choice
with its alternatives scored the same way (rows R-n), the smaller reasons behind individual rules, and what is
still open. `ir-spec.md` itself only describes the result.

## Goal and principles

**Goal.** The IR holds everything the circuit part of a SPICE deck needs (subcircuits, instances, nets,
parameters) in the structure it *should* have. Not the simulator's flat internal form: hierarchy, parameter
expressions and names must survive. Not the simulation setup either: the same circuit goes to LVS.

**Lens.** The IR models circuit concepts properly; dialects are only how we spell them. A legacy
limitation of SPICE or of a tool (no buses, case folding, line order) is handled by the writer for that tool,
never by bending the IR.

**What belongs in the IR**, for every concept:

1. every consumer would compute it the same way: the producer resolves it once (generators, loops, build
   parameters, PortRefs, bundles, name choice stay in the HDL);
2. a consumer needs it and can't derive it: it is in the IR;
3. a consumer can derive it cheaply: it is left out;
4. only one dialect or tool has it: writer option, not IR.

**What is left out, and why:**

| Concept | Why not | Where instead |
| --- | --- | --- |
| Analyses, options, saves, includes, `.model` cards, `.ic`/`.nodeset`, temperature, corners, raw lines | Setup of one simulation, not the circuit (R-21) | Simulation setup structure |
| Reference node (ground, `0`) | Which net is the reference is a fact about a simulation (R-12) | The setup names a net of the top cell |
| Global nets | Hidden wiring; ports say the same thing explicitly (R-12) | Ports; readers turn imported globals into ports |
| Inherited connections, hierarchical net references | Connectivity that depends on where a cell is used | HDL convenience, resolved to ports |
| Libraries, namespaces | Names are unique and final (R-2) | HDL naming (generator name formats) |
| Top cell | Derivable: the cells nobody instantiates | Writer input |
| Purpose (layout / simulation) | Derivable from what the CDL writer is asked to write (R-7) | The CDL writer rejects built-ins |
| Port direction | No consumer; analog pins are mostly bidirectional (R-13) | Optional field later (additive) |
| Descriptions, generic metadata | No consumer today | Typed optional fields when one appears |

## Criteria (most important first)

1. **C1 Wrong states can't be represented.**
2. **C2 One representation per circuit.**
3. **C3 Fewest rules.**
4. **C4 Matches how designers think.**
5. **C5 Simple for writers and readers.**

Scores: ++ strong, + good, 0 neutral, - weak, -- poor. **Veto** marks a practical blocker outside the criteria
(scaling, editing, correctness of output).

## Netlist and cells

### R-1 Container and references

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Libraries containing cells, instances refer by `CellRef(library, cell)` (hdlkit) | - | + | - | 0 | 0 | Two-level lookup, extra ordering rule for libraries |
| b. Object graph: an instance holds the cell object | ++ | + | ++ | + | - | **Veto**: shared cells make `==`/`hash` blow up exponentially; changing one cell means rebuilding every ancestor |
| c. Flat list of cells, instances refer by unique name | + | + | + | + | ++ | Same shape as every netlist format |
| d. vlsir: package with modules + external modules, local/external references | 0 | + | - | 0 | 0 | Two kinds of reference for one concept |

**Choice: c.** b scores best on C1/C3 but is vetoed.

### R-1b Name of the container

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Package` (hdlkit, vlsir) | 0 | 0 | 0 | - | 0 | Confusing next to Python packages |
| b. `Design` | 0 | 0 | 0 | - | 0 | Suggests one circuit with a top |
| c. `Netlist` | 0 | 0 | 0 | + | + | Exactly what a netlist file is: subcircuits calling each other by name; free since R-5 |
| d. `Circuit` | 0 | 0 | 0 | 0 | 0 | Suggests a single circuit |

**Choice: c.** Naming only; the criteria hardly separate the options.

### R-2 Cell identity and naming

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Library + cell name, writer resolves netlist-name clashes | 0 | 0 | - | + | - | Every writer needs clash handling |
| b. Unique final names in the IR; the HDL settles names (strict, generator name formats) | + | ++ | + | + | ++ | Writers print names as they are |
| c. Object identity, names assigned at write time | ++ | - | 0 | 0 | - | Names unstable across runs |

**Choice: b.** Clashes with names inside foreign IP are handled in the HDL (`occupies=`, `h.prefixed`).

### R-3 Cell order in the netlist

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Leaves first, required (define before use) | + | 0 | + | 0 | ++ | One rule, which also excludes cycles; writers emit in one pass |
| b. Any order, cycles forbidden | + | 0 | + | 0 | + | One rule (no cycles); every writer sorts first |

C1 to C4 tie (both one rule; both allow several valid orders of the same cells). C5 decides: leaves first saves
every consumer a sort, and the HDL produces that order anyway.

**Choice: a.**

### R-4 Ports and signals

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. One signal list per cell, `ports` are names into it (vlsir, hdl21) | - | + | - | 0 | + | Needs "ports name existing signals, no duplicates" and "externals have only port signals" |
| b. `Cell.ports: Signal...` in pin order, internal signals in `Netlist.signals` (hdlkit) | ++ | + | + | + | + | One rule: port and signal names unique together. An external cell can't have internals |
| c. One list of signals with a port flag and pin position | - | - | - | - | 0 | Pin order as numbers invites gaps and duplicates |

**Choice: b.** With R-5 the internal signals live on `Subckt`. Wins C1, C3 and C4; the only cost is that "all nets of a cell" is
`ports + signals` instead of one list.

### R-4b Internal signals declared or implicit

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Declared in `Netlist.signals`, with ranges | + | - | 0 | + | + | Bus width and direction stated; typos caught. An unused declared signal is a second spelling of the same circuit |
| b. Implicit: nets are the names connections mention (SPICE) | - | + | - | 0 | - | Whole-bus connections can't give a width; `<3:0>` vs `<0:3>` must be guessed; a typo silently makes a new net |

**Choice: a.** An unused internal signal is a warning, not an error. Explicit declaration follows from wanting
bus connections, and it also catches typos.

### R-5 Kinds of cell

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. One `Cell` with `body: Netlist \| External` (hdlkit) | ++ | ++ | ++ | + | 0 | Extra nesting level: `cell.body.instances` |
| b. Two flat classes: `Subckt(name, ports, params, signals, instances)` and `External(name, ports, params, element)`; `Netlist.cells: Subckt \| External` | ++ | ++ | ++ | ++ | + | Same safety without nesting; `name, ports, params` repeated in both |
| c. One flat `Cell` with optional `element`, `signals`, `instances` | - | 0 | - | + | + | A device with instances can be built; needs a rule |

**Choice: b.** It keeps a's safety and drops the nesting.

### R-6 How an external cell is called

Every `External` cell names something defined outside the netlist; `element` says where that name lives.

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `kind` (primitive/device/subckt) + `spice_type` (hdlkit) | -- | + | -- | 0 | 0 | Invalid combinations need two rules |
| b. One `element`: `subckt` (name in an included netlist), `mos`/`diode`/`bipolar`/`resistor`/`capacitor`/`inductor` (name is a PDK model), `builtin` (name is in the simulator's own vocabulary). No built-in list in the spec | ++ | ++ | ++ | + | + | Built-ins are declared like PDK devices, per dialect; each writer rejects built-ins it doesn't know |
| c. One `element` with a member per built-in (`vdc`, `ideal_resistor`, ...) | ++ | ++ | + | 0 | + | The IR fixes a built-in list that every simulator must support; awkward names next to the model elements |

**Choice: b.** The IR must fit a simulator with barely any built-ins, so the IR knows no built-ins. `builtin`
plus a name is no more magic than `mos` plus `nch`.

Why keep `element` although Spectre ignores it: a Spectre instance names its master
and Spectre resolves it itself (primitive, model or subckt), so the element letter means nothing there. CDL,
ngspice and Xyce make the writer choose the element letter, and `M1 ... nch` versus `X1 ... nch` are
different statements; which one is right depends on the PDK's model files, which are not in the IR. Needed by a
consumer and not derivable, so it stays (inclusion rule 2). The Spectre writer still uses `builtin` to know when
to apply its built-in table.

Built-ins per simulator, no spicule standard set: a portable set would make spicule own
the meaning of every source and translate it per simulator (pulse parameter order and defaults, sine phase units,
AC conventions differ), with only the common denominator available. Instead each dialect ships its own built-ins
under the simulator's names and parameters, and its writer rejects unknown names. Cost: a testbench with built-ins
is tied to one simulator, as its setup already is; designs without built-ins stay portable. A portable helper in
the HDL can be added later without changing the IR.

The list follows one rule: one value per kind of netlist line, so `subckt` (X), `builtin`, and one per SPICE
element letter that takes a model name. More such letters (`jfet` J, switches S/W, lossy lines O) can be added as
new members without breaking anything.

### R-7 Purpose (layout / simulation)

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Netlist.purpose` with rules (no ground or built-ins in layout cells) | + | + | - | + | + | Two rules, information derivable |
| b. None: the CDL writer is given a top and refuses built-ins below it | + | + | ++ | 0 | + | |

**Choice: b.** With R-6, the CDL writer rejects built-ins because its built-in table is empty.

## Nets and connections

### R-8 Buses

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `Range(msb, lsb)`, Cadence-style, either direction | + | + | 0 | ++ | + | Keeps index offset and pin order (`d<3:0>` vs `d<0:3>`) |
| b. Width only (vlsir) | + | + | + | - | - | Loses offset and order: vlsir's open ordering FIXME |
| c. No buses, net names like `d<3>` | - | 0 | + | - | - | Every tool reparses names (the SPICE limitation) |

**Choice: a.**

### R-8b A bus that is partly port, partly internal

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. No: a name is one net, port or internal, scalar or bus | + | + | + | 0 | + | Split halves get different names (`d`, `d_hi`) |
| b. Yes, per bit (Virtuoso allows pin `d<3:0>` plus wire `d<7:4>`) | - | - | -- | + | - | Uniqueness and range rules per bit instead of per name |

**Choice: a.** A future netlist reader meeting a split Virtuoso bus renames one half.

### R-9 Connections

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Flat bit list per port | ++ | ++ | ++ | -- | + | Loses "bus to port" intent |
| b. Pieces (slices, no-connects), canonical form required | + | ++ | - | + | + | Non-canonical splits are invalid (extra rule) |
| c. Pieces in any split, equality by expanded bits, producers write canonical form | + | 0 | + | + | 0 | Structurally many spellings, semantically one; custom `==`/hash expands every bit |
| d. vlsir: signal / slice / nested concat | - | - | - | + | - | Nesting, three kinds for one idea |

**Choice: b.** It beats c on C2 (one representation, identical JSON, plain `==` without expanding bits) and loses only one rule; c's argument (readers
failing on a split) disappears because every producer calls `canonicalize()`. Note: strictly by criteria order a
wins (best on C1-C3); it is overridden on the lens (bus-to-port intent is a real concept, R-8), not on the
criteria.

### R-10 Connection by port name or position

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. By port name | + | 0 | 0 | + | + | One rule: every port exactly once |
| b. By position (like a SPICE line) | + | + | + | - | 0 | Silent shifts when a port is added; poor error messages |

**Choice: a.** b scores slightly better on C2/C3 but fails on robustness;
named connections give errors like "port `d` of `inv`".

### R-11 Deliberately open bits

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `NoConnect(width)` piece | + | + | 0 | + | + | Intent visible; enables a floating-net check |
| b. Producer makes a dummy net | 0 | - | + | - | + | Intent lost; dummy names vary |

**Choice: a.**

### R-12 Ground and global nets

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Special `Ground` piece (hdlkit) | 0 | + | - | 0 | + | Needs "ground only in simulation cells" |
| b. Declared globals, ground = global `0` | 0 | 0 | - | 0 | 0 | Hidden wiring; extra declaration and rules |
| c. Neither: everything through ports; the simulation setup names the reference net | + | + | ++ | + | + | Testbenches wire `gnd` explicitly |

**Choice: c.**

### R-13 Port direction

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. None | + | + | ++ | 0 | + | Analog pins are mostly bidirectional |
| b. in / out / inout | 0 | + | - | + | 0 | No consumer; CDL `*.PININFO` optional |

**Choice: a.** Easy to add later: an optional `direction` on port signals is an additive
change within version 1 (absent = unknown). Making it required later would be version 2.

## Values

### R-14 Parameters: declaration and value

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Separate `ParamDecl(name, type, default?)` and `ParamValue(name, value)` | ++ | + | + | + | + | "Required" is expressible |
| b. One `Param(name, value)` for both (vlsir) | - | 0 | + | 0 | 0 | Can't say "required, no default" |

**Choice: a.**

### R-15 Parameter types

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Number (or expression) and string | + | + | + | + | + | What simulators take |
| b. Also bool, int, enum (vlsir) | 0 | - | - | + | - | `1` vs `1.0` vs `true` spell the same value |

**Choice: a.**

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
| a. Exact `Decimal`, no scale factors | + | ++ | + | + | + | `1.5e-6 == 0.0000015`; no rounding in generators |
| b. Float | 0 | - | + | + | + | `0.1 + 0.2 != 0.3` reaches netlists |
| c. Prefixed (vlsir) | - | -- | - | + | - | `1m` means different things per tool |

**Choice: a.**

### R-17b Plain numbers and expressions

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. A number value is a `Decimal` or an `Expression` | - | -- | 0 | + | 0 | `w = 2` can be `Decimal(2)` or `Expression(Number(2))`, which compare unequal |
| b. As a, plus a rule that an expression is never a bare number | + | ++ | - | + | 0 | Every producer must unwrap |
| c. A number value is always an `Expression`; a plain number is `Expression(Number(...))` | ++ | ++ | ++ | 0 | + | One representation and one writer path; verbose by hand (a helper covers it) |
| d. Separate parameter types for literal numbers and expressions | 0 | 0 | -- | 0 | - | No simulator distinguishes them |

**Choice: c.**
`Decimal` stays as the storage of every number, inside `Number` leaves, so `0.075` and `7.5e-2` still compare
equal.

### R-18 Expressions

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Text (hdlkit, vlsir) | - | -- | 0 | + | - | `w*2 != w * 2`; every writer parses |
| b. Text with one canonical spelling | 0 | + | - | 0 | - | Every producer must emit exactly that spelling |
| c. Tree, text only in JSON and the HDL | ++ | + | + | + | ++ | |

**Choice: c.** Implementation cost is small: ~200 lines, mostly ported from hdlkit; text would need the same parser in the validator and every writer.

## Cross-cutting

### R-19 Equality and order

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Order part of the value (tuples), producers emit deterministic order | 0 | 0 | ++ | 0 | ++ | Same circuit in two orders compares unequal |
| b. Order-free collections (mappings / frozensets) | + | ++ | 0 | 0 | - | Writers need a sort rule anyway for stable output |

**Choice: a.** Port and piece order always carry meaning. Comparing netlists from two
different producers (e.g. HDL vs a netlist reader) uses an order-insensitive helper.

### R-20 Names

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Identifier grammar, case-sensitive; the CDL writer rejects case-only clashes | + | + | + | + | + | |
| b. Identifier grammar, unique ignoring case (hdlkit) | + | + | 0 | 0 | + | A Calibre limitation in the IR |
| c. Any string, writers escape | - | 0 | + | + | -- | Escaping rules in every writer |

**Choice: a.**

### R-21 Scope of the IR

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. Circuit only; simulation setup is a separate structure | + | + | + | + | + | Same circuit goes to LVS untouched |
| b. Circuit plus analyses, includes, options | 0 | 0 | - | 0 | 0 | LVS writers must ignore half the IR |
| c. Simulator-internal flat form | - | + | + | -- | - | Loses hierarchy, expressions and names |

**Choice: a.**

### R-22 Source locations

| Alternative | C1 | C2 | C3 | C4 | C5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| a. `source` fields on cells and instances, ignored by `==` (hdlkit) | + | 0 | - | 0 | + | Ad hoc exception: non-circuit fields, special equality, own rules and path logic |
| b. Separate origin table passed alongside the netlist | + | + | + | 0 | - | Plumbing everywhere; goes stale when a transform renames or restructures |
| d. Typed `meta` field on cells and instances, one documented rule | + | + | 0 | 0 | + | One principled exception; risk of becoming a dumping ground |
| e. Origin table in a slot on `Netlist` | + | 0 | 0 | 0 | + | b's staleness plus a's exception |
| f. Nothing in the IR; each producer maps errors back to its own input | + | ++ | ++ | 0 | + | `elaborate()` keeps its own name-to-line map and annotates validation errors; writer errors name unique cells and instances |

| g. Flat `origin: str` on cells and instances, one rule | + | + | + | + | + | Each future annotation adds another exception to list |
| h. `meta: Meta` on cells and instances; `Meta` is typed (starts with `origin: str`); one structural rule: everything is compared except `meta` | + | + | + | + | ++ | Like MLIR locations / LLVM metadata; new annotations go inside `Meta` without touching any rule |

**Choice: h.** Source lines should be available in written netlists. The two objections to a metadata bag
are answered by: (1) `origin` is an uninterpreted, producer-written
string, so no definition of "location" is needed and new producers can't break it; (2) only the nodes of the
hierarchy (cells and instances) have `meta`, because they are what a hierarchical path consists of and what
becomes a statement in a netlist. `Meta` is a typed class, not a dictionary; anything that changes output other
than comments is circuit information and never goes in `Meta`. A separate table (b, e) was rejected because it
goes stale under transforms.

## Reasons behind individual rules

Smaller choices that don't need a scored row:

| Spec | Choice | Why |
| --- | --- | --- |
| 1.1 | Required fields have no "unspecified" value | vlsir's proto3 defaults silently meant INPUT, SUBCKT and 1e-24 |
| 1.2 | Frozen dataclasses; enums never equal strings | Values can be shared, hashed and compared safely; a bare string in place of an enum member is caught |
| 3 | Identifier alphabet `[A-Za-z_][A-Za-z0-9_]*` | A deliberate portable alphabet, legal unescaped in Spectre, CDL, ngspice, Xyce and GDS, so no writer needs escaping rules for names |
| 4, D-2 | Define before use | Excludes cycles in the same rule, and writers emit in one pass (R-3) |
| 5 | No built-in list in the IR; built-ins per dialect | The IR must fit any simulator, including one with barely any built-ins; no translation of source semantics between simulators (R-6) |
| 6.1 | Ranges, not widths | Index offset and order both matter (pin order, layout pin names `d<3>`); a width loses them (R-8) |
| 6.2 | `NoConnect` | "Open on purpose" is design intent; a floating-net check needs it (R-11) |
| 8 | `meta` only on cells and instances; `origin` an uninterpreted string | The hierarchy's nodes are what paths and netlist statements consist of; producers define their own notion of location (R-22) |
| C-1 | Every port connected exactly once | A missing port is an error, never an implicit open |
| 6.3 | Canonical form required | Plain dataclass equality, one JSON form per circuit, no bit expansion on every comparison (R-9) |
| 6.3 | Floating nets are warnings | A spare net is harmless and handy while editing |
| A-5 | Instance expressions only see the containing cell's parameters | No silent inheritance from enclosing scopes (Spectre would allow it) |
| A-6 | Defaults only refer to earlier parameters | Evaluation order is obvious; no cycles |
| 7.1 | No bool or int parameter types | Simulators take numbers and strings; a flag is 0/1 (R-15) |
| 7.2 | Unary `+` dropped | Otherwise `+w` and `w` would be different trees |
| 7.2 | Functions `abs sqrt exp ln log10 min max` | Only functions every dialect has with the same meaning; `log` left out because tools disagree on its base |
| F-3 | `Number` values are never negative; negation is always `Neg` | Otherwise `-1` has two trees, `Number(-1)` and `Neg(Number(1))` (C2); the parser only produces the second |
| 7.3 | No scale factors | Calibre reads `M` as milli, other tools as mega |
| 7.3 | Engineering notation (exponent a multiple of 3, unpadded; plain when the exponent is 0) | Every exponent maps onto a familiar prefix (`e-6` is u, `e3` is k); exact, and equal numbers still always print the same |
| 10 | The JSON module isn't called `json` | It would shadow the standard library in user code |

## Open

| | Question | When |
| --- | --- | --- |
| Q-6 | Does one device declaration serve both Spectre and CDL in the PDK? Check one real MOS line in each. | Start of the Spectre writer step |
