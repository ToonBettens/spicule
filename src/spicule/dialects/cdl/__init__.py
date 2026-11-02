"""CDL (Calibre SPICE): `write()` turns a netlist into CDL text (`writer`), and `builtins` declares CDL's own
elements."""

from spicule.dialects.cdl.writer import write

__all__ = ["write"]
