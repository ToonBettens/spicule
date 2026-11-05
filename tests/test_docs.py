"""The examples in the docs run, and print what the docs say they print."""

import contextlib
import io
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BLOCK = re.compile(r"^```python\n(.*?)^```\n(?:\n```text\n(.*?)^```\n)?", re.M | re.S)


@pytest.mark.parametrize("path", ["README.md", "docs/guide.md"])
def test_examples(path: str):
    """Python blocks share one namespace per file. A `text` block right after one is its output."""
    file = ROOT / path
    source = file.read_text()
    namespace: dict = {"__name__": "__main__"}
    for block in BLOCK.finditer(source):
        padding = "\n" * source.count("\n", 0, block.start(1))  # So that errors point at the line in the file.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(padding + block[1], str(file), "exec"), namespace)
        if block[2] is not None:
            assert out.getvalue().strip() == block[2].strip()
