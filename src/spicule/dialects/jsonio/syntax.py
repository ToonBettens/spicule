"""What the file format is, shared by the writer and the reader."""

#: What a file says it is: the format and its version.
NETLIST_FORMAT = "spicule.ir/1"
SIMULATION_FORMAT = "spicule.sim/1"


class FormatError(ValueError):
    """Text that isn't a netlist or simulation file: not JSON, another format or version, or the wrong shape."""
