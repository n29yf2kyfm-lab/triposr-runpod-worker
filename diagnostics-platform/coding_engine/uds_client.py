"""
UDS client — thin wrapper over `udsoncan` that speaks to an ISO-TP stack.

Exposes just the services the coding engine needs:
  0x10 DiagnosticSessionControl   — enter extended/programming session
  0x22 ReadDataByIdentifier       — read a coding block / live value
  0x2E WriteDataByIdentifier      — write a coding block
  0x31 RoutineControl             — adaptations / calibrations
  0x27 SecurityAccess             — unlock (algorithm supplied by security.py)
  0x19 ReadDTCInformation         — stored fault codes per ECU
"""
from __future__ import annotations

from typing import List, Optional

import isotp
import udsoncan
from udsoncan.client import Client
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.services import (
    DiagnosticSessionControl as DSC,
)

from .security import SecurityProvider


class UdsClient:
    def __init__(self, stack: isotp.NotifierBasedCanStack,
                 security: Optional[SecurityProvider] = None):
        self._conn = PythonIsoTpConnection(stack)
        self._security = security
        self._client = Client(self._conn, request_timeout=3)

    def __enter__(self) -> "UdsClient":
        self._client.open()
        return self

    def __exit__(self, *exc):
        self._client.close()

    # --- sessions ----------------------------------------------------------
    def extended_session(self):
        self._client.change_session(DSC.Session.extendedDiagnosticSession)

    def programming_session(self):
        self._client.change_session(DSC.Session.programmingSession)

    # --- security access (0x27) -------------------------------------------
    def unlock(self, level: int, vin: str, ecu_key: str):
        """
        Perform seed->key. The algorithm/token is NOT in this repo — it is
        provided by a SecurityProvider you configure with your licensed data.
        """
        if self._security is None:
            raise PermissionError(
                f"ECU {ecu_key} requires security level {level} but no "
                f"SecurityProvider is configured. Supply your licensed algorithm."
            )
        seed = self._client.request_seed(level).service_data.seed
        key = self._security.compute_key(ecu_key=ecu_key, level=level, seed=seed, vin=vin)
        self._client.send_key(level, key)

    # --- coding reads/writes ----------------------------------------------
    def read_did(self, did: int) -> bytes:
        resp = self._client.read_data_by_identifier(did)
        return bytes(resp.service_data.values[did])

    def write_did(self, did: int, data: bytes):
        self._client.write_data_by_identifier(did, data)

    def routine_start(self, routine_id: int, data: bytes = b""):
        self._client.start_routine(routine_id, data)

    # --- fault codes (0x19) -----------------------------------------------
    def read_dtcs(self, status_mask: int = 0xFF) -> List[str]:
        resp = self._client.get_dtc_by_status_mask(status_mask)
        return [f"{d.dtc.id:06X}" for d in resp.service_data.dtcs]

    def clear_dtcs(self, group: int = 0xFFFFFF):
        self._client.clear_dtc(group)
