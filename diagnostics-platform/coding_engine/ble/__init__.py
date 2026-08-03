"""BLE dongle layer — connect a phone/laptop to an OBD dongle. See BLUETOOTH.md."""
from .elm327 import Elm327
from .dongle_registry import DongleProfile, REGISTRY

__all__ = ["Elm327", "DongleProfile", "REGISTRY"]
