"""
BLE transport for OBD dongles (Python / laptop side, via `bleak`).

Scans for a dongle, connects, resolves the write/notify characteristics from the
registry (or by probing), and presents the `ByteStream` interface that elm327.py
consumes. Async throughout (bleak is async).

    pip install bleak
"""
from __future__ import annotations

import asyncio

from bleak import BleakClient, BleakScanner

from .dongle_registry import DongleProfile, REGISTRY, looks_like_obd, match_by_service


class BleDongle:
    def __init__(self, address: str, profile: DongleProfile):
        self.address = address
        self.profile = profile
        self._client = BleakClient(address)
        self._buf = bytearray()
        self._evt = asyncio.Event()

    # --- discovery ---------------------------------------------------------
    @classmethod
    async def discover(cls, timeout: float = 8.0) -> "BleDongle | None":
        """Find the first plausible OBD dongle and match a profile."""
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for dev, adv in devices.values():
            profile = match_by_service(adv.service_uuids or [])
            if profile is None and looks_like_obd(dev.name):
                profile = REGISTRY[0]   # best-guess common clone; probing confirms
            if profile:
                return cls(dev.address, profile)
        return None

    # --- connection --------------------------------------------------------
    async def connect(self):
        await self._client.connect()

        def _on_notify(_char, data: bytearray):
            self._buf.extend(data)
            if b">" in self._buf:
                self._evt.set()

        await self._client.start_notify(self.profile.notify_char, _on_notify)

    async def disconnect(self):
        try:
            await self._client.stop_notify(self.profile.notify_char)
        finally:
            await self._client.disconnect()

    # --- ByteStream interface (consumed by Elm327) -------------------------
    async def write(self, data: bytes) -> None:
        self._buf.clear()
        self._evt.clear()
        await self._client.write_gatt_char(
            self.profile.write_char, data,
            response=self.profile.write_with_response,
        )

    async def read_until_prompt(self, timeout: float = 5.0) -> str:
        """Wait until the '>' prompt arrives (or timeout — used to bound monitor())."""
        try:
            await asyncio.wait_for(self._evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass  # monitor mode never sends '>'; timeout is the intended stop
        text = self._buf.decode("ascii", errors="ignore")
        self._buf.clear()
        self._evt.clear()
        return text

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()
