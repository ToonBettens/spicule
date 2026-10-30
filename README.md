# spicule

Analog circuit description in Python, for Spectre simulation and Calibre LVS.

| Layer | What | Depends on |
| --- | --- | --- |
| `spicule.hdl` | What designers write: modules, ports, signals, parameters, generators. Elaborates to `spicule.ir`. | `ir` |
| `spicule.ir` | The resolved circuit: frozen dataclasses, one validator, stored as JSON. | nothing |
| `spicule.dialects` | One module per external format (Spectre, CDL, ngspice, Xyce): writers now, readers later. | `ir` |

```python
import spicule.hdl as h
```

`tests/test_layering.py` enforces the dependency arrows.

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run ty check
```
