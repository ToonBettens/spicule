"""Source lines and errors: HDL objects remember the line that created them, and errors point there."""

import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from spicule.ir import IDENTIFIER, is_identifier

_PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Source:
    """A line of Python code. `file` is the path as Python reports it."""

    file: str
    line: int

    def text(self, root: Path | None = None) -> str:
        """
        `file:line`, with the file relative to `root`. Without `root`, relative to the file's project: the nearest
        directory with a `pyproject.toml`, or else the directory above its top-level package.
        """
        path = Path(self.file)
        if not path.is_absolute() or not path.exists():
            return f"{self.file}:{self.line}"  # <stdin>, <string>, ...
        path = path.resolve()
        base = root.resolve() if root is not None else _project(path.parent)
        try:
            return f"{path.relative_to(base).as_posix()}:{self.line}"
        except ValueError:
            return f"{path.as_posix()}:{self.line}"

    def __str__(self) -> str:
        return self.text()


@cache
def _project(directory: Path) -> Path:
    project = next((d for d in (directory, *directory.parents) if (d / "pyproject.toml").is_file()), None)
    if project is None:  # Above the top-level package.
        project = directory
        while (project / "__init__.py").is_file():
            project = project.parent
    return project


@cache
def _in_package(filename: str) -> bool:
    return Path(filename).resolve().is_relative_to(_PACKAGE_DIR)


def caller() -> Source | None:
    """The first stack frame outside `spicule.hdl`: the user's line."""
    frame = sys._getframe(1)
    while frame is not None:
        if not _in_package(frame.f_code.co_filename):
            return Source(frame.f_code.co_filename, frame.f_lineno)
        frame = frame.f_back
    return None


class HdlError(Exception):
    """An error in an HDL description, pointing at the lines that caused it."""

    def __init__(self, message: str, *sources: Source | None):
        self.message = message
        self.sources = [s for s in sources if s is not None]
        text = message + "".join(f"\n  at {s}" for s in self.sources)
        super().__init__(text)


class HdlWarning(UserWarning):
    """A warning about an HDL description, such as a floating net (`elaborate(..., lint=True)`)."""


def check_identifier(name: object, what: str, source: Source | None) -> str:
    """`name` if it is an identifier, else an `HdlError` about `what`."""
    if not is_identifier(name):
        raise HdlError(f"{what} {name!r} is not an identifier ({IDENTIFIER})", source)
    return name
