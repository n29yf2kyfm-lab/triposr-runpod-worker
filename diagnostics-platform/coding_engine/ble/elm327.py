"""
ELM327 / STN AT-command protocol over an async byte stream.

Transport-agnostic: give it an object with `async write(bytes)` and an async
`readline_until_prompt()` (the BLE dongle in ble_dongle.py provides this). ELM327
speaks lines terminated with '\r'; responses end at the '>' prompt.

Handles: init sequence, OBD queries (mode 01/03/09), setting CAN headers for raw
UDS sends, and monitor mode for reverse-engineering capture (STN dongles).
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol


class ByteStream(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def read_until_prompt(self, timeout: float = 5.0) -> str: ...


class Elm327:
    def __init__(self, stream: ByteStream, is_stn: bool = False):
        self._s = stream
        self.is_stn = is_stn

    async def command(self, cmd: str, timeout: float = 5.0) -> str:
        await self._s.write((cmd + "\r").encode("ascii"))
        raw = await self._s.read_until_prompt(timeout)
        return raw.replace("\r", "\n").replace(">", "").strip()

    async def initialize(self, protocol: str = "0") -> dict:
        """Standard ELM327 init. protocol '0'=auto, '6'=ISO15765 11bit/500k, '7'=29bit/500k."""
        seq = [
            ("ATZ", 2.0),      # reset
            ("ATE0", 1.0),     # echo off
            ("ATL0", 1.0),     # linefeeds off
            ("ATS0", 1.0),     # spaces off
            ("ATH1", 1.0),     # headers on (needed to see CAN ids)
            (f"ATSP{protocol}", 1.0),
        ]
        out = {}
        for cmd, t in seq:
            out[cmd] = await self.command(cmd, t)
        return out

    # --- OBD (diagnostics) -------------------------------------------------
    async def obd(self, service_pid: str) -> str:
        """e.g. '0100', '03' (DTCs), '0902' (VIN). Returns raw hex response text."""
        return await self.command(service_pid)

    async def read_dtcs(self) -> list[str]:
        resp = await self.obd("03")
        return _parse_dtcs(resp)

    # --- raw CAN / UDS -----------------------------------------------------
    async def set_header(self, header_hex: str):
        """ATSH — set the tx CAN id (physical ECU request id) for raw sends."""
        await self.command(f"ATSH{header_hex}")

    async def set_rx_filter(self, resp_hex: str):
        await self.command(f"ATCRA{resp_hex}")

    async def send_raw(self, data_hex: str, timeout: float = 5.0) -> str:
        """
        Send a raw payload to the current header. For UDS the dongle auto-formats
        the ISO-TP single frame; multi-frame RECEIVE is auto-handled, multi-frame
        SEND needs an STN dongle (ELM327 v1.x is limited). See BLUETOOTH.md.
        """
        return await self.command(data_hex, timeout)

    # --- reverse-engineering capture --------------------------------------
    async def monitor(self, on_frame: Callable[[str, bytes], Awaitable[None] | None],
                      duration: float = 30.0):
        """
        Stream all CAN frames for `duration` seconds.
        STN: 'STMA' (monitor all) is reliable. ELM327: 'AT MA' (best-effort).
        Each line 'ID DD DD ..' is parsed to (id_hex, data_bytes) → on_frame.
        """
        cmd = "STMA" if self.is_stn else "AT MA"
        await self._s.write((cmd + "\r").encode("ascii"))
        # ble_dongle streams notify lines into read_until_prompt; here we loop until
        # duration elapses (the dongle layer enforces the time bound and cancels).
        text = await self._s.read_until_prompt(timeout=duration)
        for line in text.splitlines():
            parsed = _parse_frame(line)
            if parsed:
                res = on_frame(*parsed)
                if hasattr(res, "__await__"):
                    await res


# --- parsing helpers --------------------------------------------------------

def _parse_frame(line: str):
    parts = line.strip().split()
    if len(parts) < 2:
        return None
    can_id = parts[0]
    if not all(c in "0123456789abcdefABCDEF" for c in can_id):
        return None
    try:
        data = bytes(int(b, 16) for b in parts[1:])
    except ValueError:
        return None
    return can_id.upper(), data


def _parse_dtcs(resp: str) -> list[str]:
    """Decode a mode 03 response ('43 01 33 ...') into P/C/B/U codes."""
    hexes = resp.replace("\n", " ").split()
    hexes = [h for h in hexes if len(h) == 2]
    codes: list[str] = []
    if "43" in hexes:
        hexes = hexes[hexes.index("43") + 1:]
    for i in range(0, len(hexes) - 1, 2):
        a, b = int(hexes[i], 16), int(hexes[i + 1], 16)
        if a == 0 and b == 0:
            continue
        letter = "PCBU"[(a & 0xC0) >> 6]
        codes.append(f"{letter}{(a >> 4) & 0x3}{a & 0xF:X}{b:02X}")
    return codes
