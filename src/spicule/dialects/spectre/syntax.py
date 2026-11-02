"""What Spectre is, as far as spicule needs it: names, reserved words, built-ins, bus bits."""

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

#: The built-in elements the writer knows, by Spectre's own names. Their declarations (ports, parameters) live with
#: the HDL; a netlist carries them as `External` cells with `element=builtin`.
BUILTINS = frozenset(["resistor", "capacitor", "inductor", "vsource", "isource", "vcvs", "vccs", "ccvs", "cccs"])
