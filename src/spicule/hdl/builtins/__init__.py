"""Simulator built-ins, declared as external cells."""

from spicule.hdl.external import BUILTIN, External


def builtin(name: str, ports: str) -> External:
    cell = External(name, BUILTIN, ports)
    cell.source = None
    return cell
