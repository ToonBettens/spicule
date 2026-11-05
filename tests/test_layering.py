"""The layers only import downwards: ``ir`` imports no other layer, ``dialects`` and ``hdl`` import only ``ir``."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "src" / "spicule"

# For each layer, the spicule modules it must not import.
FORBIDDEN = {
    "spicule.ir": ("spicule.hdl", "spicule.dialects", "spicule.sim"),
    "spicule.sim": ("spicule.hdl", "spicule.dialects"),
    "spicule.dialects": ("spicule.hdl",),
    "spicule.hdl": ("spicule.dialects", "spicule.sim"),
}


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(path: Path, module: str) -> set[str]:
    """Absolute names of every module imported by ``path``, with relative imports resolved."""
    is_package = path.name == "__init__.py"
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                base = base[: len(base) - node.level + is_package]
                prefix = ".".join([*base, node.module] if node.module else base)
            else:
                prefix = node.module or ""
            names.add(prefix)
            # `from spicule import hdl` imports the submodule spicule.hdl
            names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return names


def violations(root: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        module = module_name(path, root)
        for layer, forbidden in FORBIDDEN.items():
            if module != layer and not module.startswith(layer + "."):
                continue
            for name in sorted(imported_modules(path, module)):
                if any(name == f or name.startswith(f + ".") for f in forbidden):
                    found.append(f"{module} imports {name}")
    return found


def test_layers_import_downwards():
    assert violations(PACKAGE) == []


def test_checker_finds_planted_violations(tmp_path: Path):
    root = tmp_path / "spicule"
    for layer in ("ir", "dialects", "hdl"):
        (root / layer).mkdir(parents=True)
        (root / layer / "__init__.py").write_text("")
    (root / "ir" / "model.py").write_text("import spicule.hdl.module\n")
    (root / "dialects" / "spectre.py").write_text("from ..hdl import elaborate\n")
    (root / "hdl" / "__init__.py").write_text("from spicule import dialects\n")
    (root / "hdl" / "ok.py").write_text("from spicule.ir import model\nfrom . import ok\n")

    assert violations(root) == [
        "spicule.dialects.spectre imports spicule.hdl",
        "spicule.dialects.spectre imports spicule.hdl.elaborate",
        "spicule.hdl imports spicule.dialects",
        "spicule.ir.model imports spicule.hdl.module",
    ]
