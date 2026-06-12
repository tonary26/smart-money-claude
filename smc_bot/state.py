from datetime import datetime
from typing import TypeAlias

from smc_bot.simulation import Simulation

LastSignals: TypeAlias = dict[str, datetime]
ActiveSimulations: TypeAlias = dict[str, Simulation]
