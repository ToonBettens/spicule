"""The HDL: subckts, ports, signals, parameters and external cells, as `import spicule.hdl as h`.

`h.elaborate()` turns subckts into a validated `spicule.ir.Netlist`. Simulator built-ins are in
`spicule.hdl.builtins`, one module per dialect. This package depends only on `spicule.ir`.

What is exported here is everything a design can see: what it writes, holds or catches. The rest is internal.
"""

from spicule.hdl.elaborate import elaborate
from spicule.hdl.external import (
    BIPOLAR,
    BUILTIN,
    CAPACITOR,
    DIODE,
    INDUCTOR,
    MOS,
    RESISTOR,
    SUBCKT,
    External,
)
from spicule.hdl.nets import Concat, Connectable, NoConn, Port, Ports, Signal, Signals, Slice
from spicule.hdl.params import Param, ParamExpr, fn
from spicule.hdl.source import HdlError, HdlWarning, Source
from spicule.hdl.subckt import CellCall, Instance, Subckt, SubcktInfo, info, new_subckt

__all__ = [
    "BIPOLAR",
    "BUILTIN",
    "CAPACITOR",
    "DIODE",
    "INDUCTOR",
    "MOS",
    "RESISTOR",
    "SUBCKT",
    "CellCall",
    "Concat",
    "Connectable",
    "External",
    "HdlError",
    "HdlWarning",
    "Instance",
    "NoConn",
    "Param",
    "ParamExpr",
    "Port",
    "Ports",
    "Signal",
    "Signals",
    "Slice",
    "Source",
    "Subckt",
    "SubcktInfo",
    "elaborate",
    "fn",
    "info",
    "new_subckt",
]  # fmt: skip
