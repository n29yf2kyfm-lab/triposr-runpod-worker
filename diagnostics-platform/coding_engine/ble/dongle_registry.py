"""
Known BLE OBD dongles and their GATT UART service/characteristic UUIDs.

BLE OBD dongles expose a "serial over BLE" pattern: one characteristic you WRITE
commands to, one you get NOTIFY responses from (sometimes the same one). Vendors
use different UUIDs, so we try a registry and fall back to auto-detection.

UUIDs are the commonly-documented ones; verify against your specific hardware with
`re_tools`/a BLE scanner. Add yours here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DongleProfile:
    name: str
    service: str        # GATT service UUID
    write_char: str     # characteristic to write AT commands to
    notify_char: str    # characteristic that notifies responses
    stn: bool = False   # STN chip → supports monitor mode / CAN filters (good for RE)
    write_with_response: bool = False


# 16-bit UUIDs are expanded to the Bluetooth base UUID form.
def _u16(x: str) -> str:
    return f"0000{x.lower()}-0000-1000-8000-00805f9b34fb"


REGISTRY: list[DongleProfile] = [
    # Vgate iCar Pro BLE / many BLE ELM327 clones — FFE0 service, FFE1 write+notify
    DongleProfile("Vgate/ELM327 FFE0", _u16("ffe0"), _u16("ffe1"), _u16("ffe1")),
    # Another very common clone family — FFF0 service, FFF2 write / FFF1 notify
    DongleProfile("ELM327 FFF0", _u16("fff0"), _u16("fff2"), _u16("fff1")),
    # OBDLink MX+/CX (STN chip) — Nordic-UART-style; good for coding + RE
    DongleProfile(
        "OBDLink STN (NUS)",
        "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
        "6e400002-b5a3-f393-e0a9-e50e24dcca9e",   # write (RX)
        "6e400003-b5a3-f393-e0a9-e50e24dcca9e",   # notify (TX)
        stn=True,
    ),
]

# Name substrings that hint at an OBD dongle during a BLE scan.
NAME_HINTS = ("obd", "elm", "vlink", "obdlink", "vgate", "icar", "viecar", "konnwei")


def match_by_service(service_uuids: list[str]) -> DongleProfile | None:
    svc = {s.lower() for s in service_uuids}
    for p in REGISTRY:
        if p.service.lower() in svc:
            return p
    return None


def looks_like_obd(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(h in n for h in NAME_HINTS)
