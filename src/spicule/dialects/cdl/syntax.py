"""What CDL is, as far as spicule needs it."""

from spicule.ir import Element

#: Bus bits with Calibre's default bus delimiter: `d<3>`.
BUS_FORMAT = "{name}<{index}>"

#: Calibre's `pow` truncates the exponent to an integer. `**` uses the real exponent, as `pow` does in the IR.
FUNCTIONS = {"pow": "({0})**({1})"}

#: The built-in elements the writer knows: their element letter, and the parameter written as the value (`R1 a b
#: 1e3`). Their declarations live with the HDL. An LVS netlist (`lvs=True`) refuses them.
BUILTINS: dict[str, tuple[str, str]] = {"resistor": ("R", "r"), "capacitor": ("C", "c"), "inductor": ("L", "l")}

#: The element letter for each kind of external cell. Subcircuits, ours and foreign, are called with `X`.
LETTERS = {
    Element.SUBCKT: "X",
    Element.MOS: "M",
    Element.DIODE: "D",
    Element.BIPOLAR: "Q",
    Element.RESISTOR: "R",
    Element.CAPACITOR: "C",
    Element.INDUCTOR: "L",
}
