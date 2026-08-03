"""
Reverse-engineering capture: log every CAN frame from a BLE dongle to CSV.

Workflow: run this, then toggle a feature with the OEM tool / press a button. Diff
two captures — the bytes that changed are your coding signal.

Best on an STN dongle (reliable monitor mode). Read-only; sends no writes.

    python -m re_tools.can_sniffer --seconds 30 --out capture_before.csv
    # (toggle the feature in the OEM tool)
    python -m re_tools.can_sniffer --seconds 30 --out capture_after.csv
    python -m re_tools.can_sniffer --diff capture_before.csv capture_after.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import time

from coding_engine.ble.ble_dongle import BleDongle
from coding_engine.ble.elm327 import Elm327


async def capture(seconds: float, out_path: str):
    dongle = await BleDongle.discover()
    if not dongle:
        print("No BLE OBD dongle found. Is it powered and in range?")
        return
    print(f"Connecting to {dongle.profile.name} @ {dongle.address} …")
    async with dongle:
        elm = Elm327(dongle, is_stn=dongle.profile.stn)
        await elm.initialize()
        rows: list[tuple[float, str, str]] = []

        def on_frame(can_id: str, data: bytes):
            rows.append((round(time.time(), 4), can_id, data.hex(" ")))

        print(f"Capturing {seconds:.0f}s … provoke the feature now.")
        await elm.monitor(on_frame, duration=seconds)

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "can_id", "data"])
        w.writerows(rows)
    print(f"✓ {len(rows)} frames → {out_path}")


def diff(before_path: str, after_path: str):
    def load(p):
        with open(p) as f:
            return list(csv.DictReader(f))
    def latest_by_id(rows):
        m: dict[str, str] = {}
        for r in rows:
            m[r["can_id"]] = r["data"]     # last value seen per id
        return m
    b, a = latest_by_id(load(before_path)), latest_by_id(load(after_path))
    print("Changed CAN ids (candidate coding signals):")
    changed = 0
    for cid in sorted(set(b) | set(a)):
        if b.get(cid) != a.get(cid):
            changed += 1
            print(f"  {cid}:  {b.get(cid,'—'):<24} →  {a.get(cid,'—')}")
    if not changed:
        print("  (none — try a longer capture, or a different bus/feature)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--out", default="capture.csv")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.diff:
        diff(*args.diff)
    else:
        asyncio.run(capture(args.seconds, args.out))


if __name__ == "__main__":
    main()
