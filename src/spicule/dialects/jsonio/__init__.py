"""JSON files for looking at netlists and simulations, comparing them and keeping them (`ir-spec.md`, section 10)."""

from spicule.dialects.jsonio.reader import read
from spicule.dialects.jsonio.syntax import FormatError
from spicule.dialects.jsonio.writer import write

__all__ = ["FormatError", "read", "write"]
