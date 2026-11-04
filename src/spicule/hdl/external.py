"""External cells: PDK devices, foreign subcircuits and simulator built-ins.

An external cell is defined elsewhere, so it declares only its name, how a netlist calls it (`element`) and its ports,
in order. A PDK package is a list of these::

    nch = h.External(
        "nch", element=h.MOS, ports=[h.Port(name="d"), h.Port(name="g"), h.Port(name="s"), h.Port(name="b")]
    )
    sram = h.External("sram", element=h.SUBCKT, ports=[h.Port(name="addr", width=6), h.Port(name="clk")])

    mn = nch(l=16e-9, nfin=4)(d=y, g=a, s=vss, b=vss)

Its parameters belong to the PDK or the simulator, with their defaults and which ones are required, so they are not
declared and any may be set. A `str` is a text value, anything else a number. Simulator built-ins are in
`spicule.hdl.builtins`.
"""

from collections.abc import Sequence
from typing import Any

from spicule import ir
from spicule.hdl.nets import Port
from spicule.hdl.params import HdlValue, Param, to_value
from spicule.hdl.source import HdlError, Source, caller, check_identifier
from spicule.hdl.subckt import CellInfo

SUBCKT = ir.Element.SUBCKT
MOS = ir.Element.MOS
DIODE = ir.Element.DIODE
BIPOLAR = ir.Element.BIPOLAR
RESISTOR = ir.Element.RESISTOR
CAPACITOR = ir.Element.CAPACITOR
INDUCTOR = ir.Element.INDUCTOR
BUILTIN = ir.Element.BUILTIN


class External(CellInfo):
    """A cell defined elsewhere. See `spicule.hdl.external`."""

    def __init__(self, name: str, *, element: ir.Element, ports: Sequence[Port] = ()):
        self.source = caller()
        self.name = check_identifier(name, "cell name", self.source)
        if not isinstance(element, ir.Element):
            raise HdlError(f"element must be one of h.SUBCKT, h.MOS, ..., h.BUILTIN, got {element!r}", self.source)
        self.element = element
        self.params: dict[str, Param] = {}
        self.ports: dict[str, Port] = {}
        for port in ports:
            if not isinstance(port, Port) or port.name is None:
                raise HdlError(f"ports of an external cell are h.Port(name=...), got {port!r}", self.source)
            if port.name in self.ports:
                raise HdlError(f"external cell {name}: duplicate port {port.name!r}", self.source)
            port.__set_name__(self, port.name)
            self.ports[port.name] = port

    def check_params(self, values: dict[str, Any], source: Source | None) -> dict[str, HdlValue]:
        """Any parameter may be set, as a number or a text."""
        checked: dict[str, HdlValue] = {}
        for name, value in values.items():
            check_identifier(name, "parameter name", source)
            checked[name] = to_value(value, f"parameter {name} of {self.name}", source)
        return checked

    def to_ir(self, origin: str | None = None) -> ir.External:
        return ir.External(
            name=self.name,
            element=self.element,
            ports=tuple(port.to_decl() for port in self.ports.values()),
            meta=ir.Meta(origin=origin),
        )

    def __repr__(self) -> str:
        return f"External({self.name})"
