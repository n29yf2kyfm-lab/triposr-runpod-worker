"""
Transport layer — CAN *and* CAN-FD, with ISO-TP (ISO 15765-2).

The whole point of this module: BMW F-series and VAG MQB speak classic CAN;
BMW G/I-series and VAG MQB-Evo/MEB speak CAN-FD. We select the bus and ISO-TP
parameters from the vehicle's `platform` profile (stored in Supabase) so the
rest of the engine never has to care which one it's on.

Requires: python-can, can-isotp
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import can
import isotp


@dataclass
class PlatformProfile:
    """Mirror of a `platform` + `ecu` row from Supabase."""
    make: str
    family: str
    bus: str                    # 'can' | 'canfd'
    can_bitrate: int = 500_000
    canfd_data_bitrate: Optional[int] = None
    # ECU addressing (from the `ecu` row)
    req_id: int = 0x6F1         # tester -> ECU (BMW commonly 0x6F1 diagnostic)
    resp_id: int = 0x612        # ECU -> tester
    addressing: str = "physical"

    @property
    def is_fd(self) -> bool:
        return self.bus == "canfd"


def open_bus(profile: PlatformProfile, channel: str = "can0",
             interface: str = "socketcan") -> can.BusABC:
    """
    Open the underlying CAN/CAN-FD interface.

    `interface`/`channel` examples:
      - Linux SocketCAN:        interface='socketcan',  channel='can0'
      - SLCAN (ELM/OBDLink):    interface='slcan',      channel='/dev/ttyUSB0'
      - Test (no hardware):     interface='virtual',    channel='vcan0'
    """
    kwargs = dict(interface=interface, channel=channel, bitrate=profile.can_bitrate)
    if profile.is_fd:
        kwargs.update(
            fd=True,
            data_bitrate=profile.canfd_data_bitrate or 2_000_000,
        )
    return can.Bus(**kwargs)


def open_isotp(bus: can.BusABC, profile: PlatformProfile) -> isotp.NotifierBasedCanStack:
    """
    Build an ISO-TP stack over the open bus, sized for CAN or CAN-FD.

    For CAN-FD we enable the flexible-datarate frame and a 64-byte tx length so
    long coding blocks transfer in a single frame where possible.
    """
    addr = isotp.Address(
        isotp.AddressingMode.Normal_11bits,
        txid=profile.req_id,
        rxid=profile.resp_id,
    )
    params = {
        "blocking_send": False,
        "tx_padding": 0x00,
        "rx_flowcontrol_timeout": 1000,
        "rx_consecutive_frame_timeout": 1000,
    }
    if profile.is_fd:
        params.update({
            "can_fd": True,
            "tx_data_length": 64,
            "tx_data_min_length": 8,
            "bitrate_switch": True,     # switch to fast data phase
        })
    notifier = can.Notifier(bus, [])
    return isotp.NotifierBasedCanStack(bus=bus, notifier=notifier, address=addr, params=params)


# --- convenience ------------------------------------------------------------

def profile_from_supabase_rows(platform_row: dict, ecu_row: dict) -> PlatformProfile:
    """Adapt the joined `platform`+`ecu` rows into a runtime profile."""
    return PlatformProfile(
        make=platform_row["make"],
        family=platform_row["family"],
        bus=platform_row["bus"],
        can_bitrate=platform_row.get("can_bitrate", 500_000),
        canfd_data_bitrate=platform_row.get("canfd_data_bitrate"),
        req_id=ecu_row["req_id"],
        resp_id=ecu_row["resp_id"],
        addressing=ecu_row.get("addressing", "physical"),
    )
