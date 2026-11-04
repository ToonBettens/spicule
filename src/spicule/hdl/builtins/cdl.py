"""CDL's built-in elements."""

from spicule.hdl.builtins import builtin

resistor = builtin("resistor", "p n")
capacitor = builtin("capacitor", "p n")
inductor = builtin("inductor", "p n")

#: Every built-in, by name.
BUILTINS = {cell.name: cell for cell in (resistor, capacitor, inductor)}
