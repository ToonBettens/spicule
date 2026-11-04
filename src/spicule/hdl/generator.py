"""Generators: a class is one cell, a decorated function is a family of cells.

A generator takes build parameters, its arguments: Python values that decide structure. It runs once per distinct
value, and each gets its own cell, named by the format on the decorator. The format uses every argument::

    @h.generator("invbank_n{n}")
    def invbank(*, n: int = 4) -> type[h.Subckt]:
        class bank(h.Subckt):
            d, q = h.Ports(2, width=n)
            vdd, vss = h.Ports(2)
            nfin = h.Param(4)

        for bit in range(n):
            setattr(bank, f"x{bit}", inv(nfin=bank.nfin)(bank.d[bit], bank.q[bit], bank.vdd, bank.vss))
        return bank


    dut = invbank(n=4)(nfin=6)(din, mid, vdd, vss)  # build parameters, netlist parameters, connections

Build parameters never reach the IR. The cell can declare netlist parameters as any cell does.
"""

import inspect
import re
import string
from collections.abc import Callable
from functools import update_wrapper
from typing import Any

from spicule.hdl.source import HdlError, Source, caller, check_identifier
from spicule.hdl.subckt import SubcktMeta, new_serial


def generator[**P, C](name: str) -> Callable[[Callable[P, C]], Callable[P, C]]:
    """A decorator that makes a function a generator, with `name` as the format of its cell names."""
    if not isinstance(name, str):
        raise HdlError('a generator needs a name format: @h.generator("inv_x{n}")', caller())

    def decorate(func: Callable[P, C]) -> Callable[P, C]:
        function = getattr(func, "__name__", "?")
        signature = inspect.signature(func)
        _check_format(name, function, signature, caller())
        cells: dict[tuple, C] = {}
        names: dict[str, tuple[str, Source | None]] = {}
        running: set[tuple] = set()

        def call(*args: P.args, **kwargs: P.kwargs) -> C:
            source = caller()
            try:
                bound = signature.bind(*args, **kwargs)
            except TypeError as error:
                raise HdlError(f"generator {function}: {error}", source) from None
            bound.apply_defaults()
            key = _key(function, bound.arguments, source)
            if key in cells:
                return cells[key]
            if key in running:
                raise HdlError(f"generator {function} calls itself with the same values: {_text(key)}", source)
            running.add(key)
            try:
                first_new = new_serial()
                cell = func(*args, **kwargs)
            finally:
                running.discard(key)
            made = _new_subckt(function, cell, first_new, source)
            cell_name = _cell_name(name, function, bound.arguments, source)
            if cell_name in names:
                other, other_source = names[cell_name]
                raise HdlError(
                    f"generator {function} named the cells for {other} and {_text(key)} both {cell_name!r}; "
                    f"tell them apart in the name format",
                    other_source,
                    source,
                )
            names[cell_name] = (_text(key), source)
            made.__hdl__.name = cell_name
            made.__hdl__.generated = True
            made.__name__ = made.__qualname__ = cell_name
            cells[key] = cell
            return cell

        return update_wrapper(call, func)

    return decorate


def _check_format(name: str, function: str, signature: inspect.Signature, source: Source | None) -> None:
    """Every argument occurs in the format, and every field is an argument."""
    parameters = signature.parameters
    if not parameters:
        raise HdlError(
            f"generator {function} has no build parameters: it always builds one cell, so write a class", source
        )
    variable = [p.name for p in parameters.values() if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    if variable:
        raise HdlError(f"generator {function}: *{variable[0]} can't be checked against the name format", source)
    try:
        fields = [field for _, field, _, _ in string.Formatter().parse(name) if field is not None]
    except ValueError as error:
        raise HdlError(f"generator {function}: bad name format {name!r}: {error}", source) from None
    roots = {re.split(r"[.\[]", field)[0] for field in fields}
    unknown = sorted(roots - set(parameters))
    if unknown:
        raise HdlError(f"generator {function}: name format {name!r} uses {unknown[0]!r}, not an argument", source)
    missing = [p for p in parameters if p not in roots]
    if missing:
        raise HdlError(f"generator {function}: name format {name!r} doesn't use the argument {missing[0]!r}", source)


def _key(function: str, arguments: dict[str, Any], source: Source | None) -> tuple:
    for name, value in arguments.items():
        try:
            hash(value)
        except TypeError:
            raise HdlError(
                f"generator {function}: argument {name}={value!r} can't be a build parameter, because it isn't "
                f"hashable; use a tuple instead of a list, for example",
                source,
            ) from None
    return tuple(arguments.items())


def _text(key: tuple) -> str:
    return ", ".join(f"{name}={value!r}" for name, value in key)


def _new_subckt(function: str, cell: object, first_new: int, source: Source | None) -> SubcktMeta:
    """`cell`, if it is a new subckt: naming a cell that existed already would rename it for everyone."""
    if not isinstance(cell, SubcktMeta) or "__hdl__" not in cell.__dict__:
        raise HdlError(f"generator {function} must return a new subckt, got {cell!r}", source)
    if cell.__hdl__.serial < first_new or cell.__hdl__.generated:
        raise HdlError(f"generator {function} must return a new subckt, got {cell!r}, which already existed", source)
    return cell


def _cell_name(name: str, function: str, arguments: dict[str, Any], source: Source | None) -> str:
    try:
        text = name.format(**arguments)
    except (ValueError, TypeError, AttributeError, LookupError) as error:
        raise HdlError(f"generator {function}: name format {name!r} fails: {error}", source) from None
    return check_identifier(text, f"generator {function}: cell name", source)
