from spicule.ir import Element, External, ParamDecl, ParamType, Signal


def _builtin(name: str, value: str) -> External:
    return External(
        name=name,
        element=Element.BUILTIN,
        ports=(Signal(name="p"), Signal(name="n")),
        params=(ParamDecl(name=value, type=ParamType.NUMBER),),
    )


resistor = _builtin("resistor", "r")
capacitor = _builtin("capacitor", "c")
inductor = _builtin("inductor", "l")

BUILTINS: dict[str, External] = {cell.name: cell for cell in (resistor, capacitor, inductor)}
