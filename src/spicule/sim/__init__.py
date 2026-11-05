"""What to do with a circuit: models to load, analyses to run, what to save (`docs/sim-spec.md`).

Apart from the IR, because the same circuit also goes to LVS (`ir-decisions.md`, R-21). Depends only on `spicule.ir`.
"""

from spicule.sim.model import Analysis, Include, Options, Param, Raw, Simulation, SimulationError, SimValue
from spicule.sim.validator import validate

__all__ = ["Analysis", "Include", "Options", "Param", "Raw", "SimValue", "Simulation", "SimulationError", "validate"]
