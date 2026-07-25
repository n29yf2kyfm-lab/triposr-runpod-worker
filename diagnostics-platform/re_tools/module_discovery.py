#!/usr/bin/env python3
"""
UDS module discovery — find EVERY ECU on the car, then read its identity.

Sweeps the diagnostic address range with UDS TesterPresent (0x3E), records which
addresses answer, then reads VIN / part number / SW version / coding via
ReadDataByIdentifier (0x22). Discovered modules can be written straight into the
`ecu` table so a scan turns an unknown car into a populated platform profile.

Based on the uploaded uds_scanner.py, with the protocol bugs fixed:
  * ATCAF1 (auto-formatting ON) so the ELM builds valid ISO-TP frames and
    reassembles multi-frame replies (e.g. the 17-byte VIN). The original CAF0 +
    no PCI byte meant real ECUs never answered.
  * header-aware parsing: with ATH1 the 11-bit responder ID is 3 hex chars, so we
    split the first token per line instead of concatenating (which mis-aligned bytes).
  * no fixed `req+8` reply filter — the responder ID is read from the header, so
    modules outside the 0x7E0 range aren't missed.
  * full 0x700-0x7FF sweep.

Read-only (services 0x3E and 0x22 only). No writes, no security bypass.

    python -m re_tools.module_discovery --wifi                 # ELM327 WiFi
    python -m re_tools.module_discovery /dev/ttyUSB0           # serial
    python -m re_tools.module_discovery --sim                  # no hardware
    python -m re_tools.module_discovery --wifi --to-supabase --platform-id <uuid>
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time

WIFI_IP, WIFI_PORT = "192.168.0.10", 35000

MODULE_NAMES = {
    0x700: "OBD legislated gateway",
    0x701: "Engine ECU (ECM)", 0x703: "ABS / ESP", 0x704: "Transmission (TCM)",
    0x706: "Instrument cluster", 0x707: "Airbag (SRS)", 0x709: "Central body / BCM",
    0x70C: "Power steering", 0x70D: "Parking brake", 0x70E: "Climate control",
    0x70F: "Door module (front left)", 0x710: "Door module (front right)",
    0x712: "Radio / infotainment", 0x713: "Adaptive cruise / radar",
    0x715: "Immobilizer / steering column lock", 0x716: "Suspension / damping",
    0x717: "Headlight / AFS", 0x718: "Tire pressure (TPMS)",
    0x719: "Parking aid", 0x71A: "Camera / lane assist",
    0x71B: "Seat memory (driver)", 0x71C: "Trailer module",
    0x71D: "Electric drive / hybrid (HEV)", 0x71E: "Charging module (EV)",
    0x71F: "Battery management (BMS)",
    0x7E0: "Engine ECU (ECM)", 0x7E1: "Transmission (TCM)",
}

IDENTIFIERS = {
    "F190": "VIN", "F187": "Spare part number", "F189": "Software version",
    "F191": "ECU hardware number", "F195": "Software fingerprint", "F1A0": "Coding / variant",
}


# ---------------------------------------------------------------- ELM327 raw
class ELM327:
    def __init__(self, ip=None, port=35000, serial_port=None):
        self.sock = None
        self.ser = None
        if serial_port:
            import serial
            self.ser = serial.Serial(serial_port, 38400, timeout=2)
        else:
            self.sock = socket.create_connection((ip, port), timeout=6)
            self.sock.settimeout(3)

    def _write(self, data):
        (self.sock.sendall if self.sock else self.ser.write)(data)

    def _read(self):
        buf, t0 = b"", time.time()
        while time.time() - t0 < 2.5:
            try:
                chunk = self.sock.recv(1024) if self.sock else self.ser.read(1024)
            except (socket.timeout, TimeoutError):
                break
            if not chunk:
                break
            buf += chunk
            if b">" in buf:
                break
        return buf.decode(errors="replace")

    def cmd(self, text, delay=0.05):
        self._write((text + "\r").encode())
        raw = self._read()
        time.sleep(delay)
        lines = []
        for ln in raw.replace("\r", "\n").split("\n"):
            ln = ln.strip().rstrip(">").strip()
            if ln and ln.upper() not in (text.upper(), "OK"):
                lines.append(ln)
        return lines

    def init_obd(self):
        # ATCAF1 (auto-formatting ON): the ELM adds the ISO-TP PCI byte and
        # reassembles multi-frame responses. ATH1 so we see the responder ID.
        for c in ("ATZ", "ATE0", "ATL0", "ATS0", "ATH1", "ATSP6", "ATCAF1"):
            self.cmd(c, 0.15)

    def uds_request(self, module_id, payload):
        """Set the request header and send a UDS service; ELM auto-formats + reassembles."""
        self.cmd(f"ATSH{module_id:03X}")
        return self.cmd(payload)


# ---------------------------------------------------------------- parsing
def parse_response(lines):
    """
    Turn ELM lines (headers on) into [(resp_id:int, data:bytes)].
    With ATH1 each line is: '<3-hex resp id> <hh> <hh> ...'. The first token is the
    responder ID; the rest are data bytes. (Fixes the original nibble misalignment.)
    """
    out = []
    for ln in lines:
        toks = ln.replace("\t", " ").split()
        if len(toks) < 2:
            continue
        head = toks[0]
        if not all(c in "0123456789abcdefABCDEF" for c in head):
            continue           # skip 'SEARCHING...', 'NO DATA', etc.
        try:
            rid = int(head, 16)
            data = bytes(int(b, 16) for b in toks[1:] if len(b) == 2)
        except ValueError:
            continue
        out.append((rid, data))
    return out


def _ascii(data):
    return "".join(chr(b) for b in data if 32 <= b < 127).strip()


# ---------------------------------------------------------------- simulation
SIM_MODULES = [
    (0x701, {"F190": "WVWZZZ3CZWE000001", "F187": "06K907425B", "F189": "0003", "F191": "06K907425"}),
    (0x703, {"F187": "5Q0614517CG", "F189": "0142", "F191": "5Q0614517"}),
    (0x704, {"F187": "09G927750GS", "F189": "0210", "F191": "09G927750"}),
    (0x706, {"F187": "5G0920740A", "F189": "0311", "F191": "5G0920740"}),
    (0x707, {"F187": "5Q0959655R", "F189": "0023", "F191": "5Q0959655"}),
    (0x712, {"F187": "5G0035820B", "F189": "0468", "F191": "5G0035820"}),
]


# ---------------------------------------------------------------- scanning
def discover(sim=False, elm=None, lo=0x700, hi=0x7FF):
    """Return {resp_id: {DID: value}} for every responding module."""
    if sim:
        return {mid: dict(data) for mid, data in SIM_MODULES}

    found = {}
    print(f"  Pinging CAN {lo:#05x}-{hi:#05x} (TesterPresent) …")
    for mid in range(lo, hi + 1):
        for rid, data in parse_response(elm.uds_request(mid, "3E00")):
            # positive response to service 0x3E is 0x7E (= 0x40 + 0x3E)
            if data and data[0] == 0x7E:
                found[rid] = {}
                print(f"    hit: req {mid:#05x} → resp {rid:#05x}  {MODULE_NAMES.get(rid, MODULE_NAMES.get(mid, 'unknown'))}")
                break
    return found


def read_idents(found, sim=False, elm=None):
    if sim:
        return found
    for rid in list(found):
        req = rid - 8 if rid >= 0x7E8 else rid            # best-effort request id
        for did in IDENTIFIERS:
            for _, data in parse_response(elm.uds_request(req, "22" + did)):
                # positive: 62 <DID hi> <DID lo> <payload…>
                if len(data) >= 3 and data[0] == 0x62:
                    val = _ascii(data[3:])
                    if val:
                        found[rid][did] = val
                    break
    return found


def to_ecu_rows(found, platform_id):
    """Shape discovered modules into `ecu` table rows."""
    rows = []
    for rid, data in sorted(found.items()):
        req = rid - 8 if rid >= 0x7E8 else rid
        rows.append({
            "platform_id": platform_id,
            "key": MODULE_NAMES.get(rid, f"MODULE_{rid:03X}").upper().replace(" ", "_").replace("/", "_"),
            "name": MODULE_NAMES.get(rid, f"Unknown module {rid:#05x}"),
            "req_id": req, "resp_id": rid,
            "safety_critical": rid in (0x703, 0x707, 0x715),   # ABS, airbag, ESL
        })
    return rows


def report(found):
    print(f"\n===== MODULE MAP — {len(found)} module(s) =====\n")
    for rid, data in sorted(found.items()):
        print(f"  {rid:#05x}  {MODULE_NAMES.get(rid, 'unknown module')}")
        for did, label in IDENTIFIERS.items():
            if data.get(did):
                print(f"        {label:<22}: {data[did]}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", help="/dev/ttyUSB0 or COM3 (serial)")
    ap.add_argument("--wifi", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--to-supabase", action="store_true")
    ap.add_argument("--platform-id")
    ap.add_argument("--json", action="store_true", help="print ecu rows as JSON")
    args = ap.parse_args()

    elm, sim = None, args.sim
    if not sim:
        try:
            if args.wifi:
                elm = ELM327(ip=WIFI_IP, port=WIFI_PORT)
            elif args.port:
                elm = ELM327(serial_port=args.port)
            else:
                raise RuntimeError("give --wifi, a serial port, or --sim")
            elm.init_obd()
        except Exception as e:
            print(f"  adapter unreachable ({e}) → simulation\n")
            sim = True

    found = read_idents(discover(sim=sim, elm=elm), sim=sim, elm=elm)
    report(found)

    if args.to_supabase:
        if not args.platform_id:
            print("  --to-supabase needs --platform-id"); return
        from coding_engine.supabase_store import get_client
        rows = to_ecu_rows(found, args.platform_id)
        get_client().table("ecu").upsert(rows, on_conflict="platform_id,key").execute()
        print(f"  ✓ wrote {len(rows)} ecu rows to Supabase")
    elif args.json:
        print(json.dumps(to_ecu_rows(found, args.platform_id or "PLATFORM"), indent=2))


if __name__ == "__main__":
    main()
