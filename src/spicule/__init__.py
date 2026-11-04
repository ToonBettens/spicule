"""spicule: analog circuit description in Python.

Three layers, with dependencies pointing one way:

- `spicule.hdl`: what designers write. Elaborates to `spicule.ir`.
- `spicule.ir`: the resolved circuit. Depends on nothing.
- `spicule.dialects`: readers and writers for external formats. Depends only on `spicule.ir`.

Designers import the HDL as `import spicule.hdl as h`. This module imports nothing, so `import spicule.ir` never loads
the HDL.
"""
