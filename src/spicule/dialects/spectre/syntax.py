"""What Spectre is, as far as spicule needs it."""

#: Bus bits as Virtuoso writes them: `d\<3\>`.
BUS_FORMAT = r"{name}\<{index}\>"

#: Netlist keywords: not allowed as subcircuit or instance names.
KEYWORDS = frozenset([
    "altergroup", "correlate", "else", "end", "ends", "export", "for",
    "function", "global", "ic", "if", "in", "inline", "input", "invisible",
    "library", "local", "march", "model", "nodeset", "out", "output",
    "parameters", "paramset", "plot", "print", "protect", "pwr", "real",
    "return", "save", "sens", "statistics", "subckt", "to", "truncate",
    "unprotect", "vary", "visible",
])  # fmt: skip

#: Mathematical and physical constants: not allowed as any name.
CONSTANTS = frozenset([
    "M_1_PI", "M_2_PI", "M_2_SQRTPI", "M_DEGPERRAD", "M_E", "M_LN10",
    "M_LN2", "M_LOG10E", "M_LOG2E", "M_PI", "M_PI_2", "M_PI_4",
    "M_SQRT1_2", "M_SQRT2", "M_TWO_PI", "P_C", "P_CELSIUS0", "P_EPS0",
    "P_H", "P_K", "P_Q", "P_U0",
])  # fmt: skip

#: Reserved words: not allowed as parameter names.
RESERVED = frozenset(["freq", "scalem", "temp", "temper", "time", "tnom"])

#: Spectre's implicit subcircuit multiplicity.
MULTIPLICITY = "m"

#: The built-in elements the writer knows, by Spectre's own names. The HDL declares them (`spicule.hdl.builtins`), and
#: a netlist carries them as `External` cells with `element=builtin`.
BUILTINS = frozenset(["resistor", "capacitor", "inductor", "vsource", "isource", "vcvs", "vccs", "ccvs", "cccs"])

#: The statements written as `name type parameters`: what `spectre -h` lists as analyses and controls, without `options`
#: (a field of its own in a simulation) and `altergroup` (a block with a circuit in it, so raw).
ANALYSES = frozenset([
    "ac", "acmatch", "alter", "check", "checklimit", "cosim", "customerrpreset", "dc", "dcmatch", "devchrz",
    "dspf_options", "envlp", "hb", "hbac", "hbnoise", "hbsp", "hbstb", "hbxf", "info", "lf", "loadpull",
    "montecarlo", "noise", "optimize", "pac", "pnoise", "psp", "pss", "pstb", "pxf", "pz", "qpac", "qpnoise",
    "qpsp", "qpss", "qpxf", "reliability", "set", "shell", "sp", "stb", "stress", "sweep", "tdr", "thermal",
    "tran", "uti", "xf",
])  # fmt: skip

#: The analyses that repeat other analyses, written as a `{ }` block around them.
ANALYSES_WITH_CHILDREN = frozenset(["montecarlo", "sweep"])
