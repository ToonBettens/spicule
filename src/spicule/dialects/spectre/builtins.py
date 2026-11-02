from spicule.ir import Element, External, ParamDecl, ParamType, Signal

_N = ParamType.NUMBER
_S = ParamType.STRING


def _builtin(name: str, ports: str, params: dict[str, ParamType]) -> External:
    return External(
        name=name,
        element=Element.BUILTIN,
        ports=tuple(Signal(name=p) for p in ports.split()),
        params=tuple(ParamDecl(name=n, type=t) for n, t in params.items()),
    )


_SOURCE = {
    "type": _S,
    "dc": _N,
    "mag": _N,
    "phase": _N,
    "delay": _N,
    "val0": _N,
    "val1": _N,
    "period": _N,
    "rise": _N,
    "fall": _N,
    "width": _N,
    "sinedc": _N,
    "ampl": _N,
    "freq": _N,
    "sinephase": _N,
}

resistor = _builtin("resistor", "p n", {"r": _N, "m": _N, "tc1": _N, "tc2": _N, "scale": _N})
capacitor = _builtin("capacitor", "p n", {"c": _N, "m": _N, "scale": _N})
inductor = _builtin("inductor", "p n", {"l": _N, "m": _N})
vsource = _builtin("vsource", "p n", _SOURCE)
isource = _builtin("isource", "sink src", _SOURCE)
vcvs = _builtin("vcvs", "p n ps ns", {"gain": _N, "m": _N})
vccs = _builtin("vccs", "sink src ps ns", {"gm": _N, "m": _N})
ccvs = _builtin("ccvs", "p n", {"rm": _N, "probes": _S, "m": _N})
cccs = _builtin("cccs", "sink src", {"gain": _N, "probes": _S, "m": _N})

BUILTINS: dict[str, External] = {
    cell.name: cell for cell in (resistor, capacitor, inductor, vsource, isource, vcvs, vccs, ccvs, cccs)
}
