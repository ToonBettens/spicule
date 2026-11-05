"""What the file format is, shared by the writer and the reader."""

#: What a netlist file says it is: the format and its version.
FORMAT = "spicule.ir/1"


class FormatError(ValueError):
    """Text that isn't a netlist file: not JSON, another format or version, or the wrong shape."""
