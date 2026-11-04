"""Simulator built-ins, declared as external cells."""

from collections.abc import Sequence

from spicule.hdl.external import BUILTIN, External
from spicule.hdl.nets import Port


def builtin(name: str, ports: Sequence[str]) -> External:
    cell = External(name, element=BUILTIN, ports=[Port(name=p) for p in ports])
    cell.source = None
    return cell
