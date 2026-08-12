"""
Reverse-engineering: sweep UDS ReadDataByIdentifier (0x22) on an ECU to find which
DIDs hold coding/config blocks. Read-only enumeration — the safe RE workhorse.

Sets the ECU header, reads a range of DIDs, records positive responses (those not
starting with 0x7F negative-response). Rate-limited to be gentle on the bus.

    python -m re_tools.uds_scan --req 6F1 --resp 672 --from 0x2E00 --to 0x2F00

Does NOT attempt SecurityAccess or any write. Run on a vehicle you own.
"""
from __future__ import annotations

import argparse
import asyncio

from coding_engine.ble.ble_dongle import BleDongle
from coding_engine.ble.elm327 import Elm327


async def scan(req: str, resp: str, did_from: int, did_to: int, delay: float):
    dongle = await BleDongle.discover()
    if not dongle:
        print("No BLE OBD dongle found.")
        return
    async with dongle:
        elm = Elm327(dongle, is_stn=dongle.profile.stn)
        await elm.initialize(protocol="6")   # ISO15765 11-bit/500k
        await elm.set_header(req)
        await elm.set_rx_filter(resp)
        print(f"Sweeping DIDs 0x{did_from:04X}..0x{did_to:04X} on ECU {req}→{resp}")

        found = []
        for did in range(did_from, did_to + 1):
            payload = f"22{did:04X}"
            r = (await elm.send_raw(payload, timeout=1.5)).replace("\n", " ").strip()
            hexes = r.split()
            # positive response to 0x22 is 0x62; negative is 0x7F
            if "62" in hexes and "7F" not in hexes[:2]:
                data = "".join(hexes)
                found.append((did, data))
                print(f"  ✓ 0x{did:04X}: {r}")
            await asyncio.sleep(delay)

        print(f"\n{len(found)} readable DIDs. Toggle a feature, re-run, and diff to find "
              f"which DID + bit owns it → record as a coding_definition.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--req", required=True, help="ECU request CAN id, e.g. 6F1")
    ap.add_argument("--resp", required=True, help="ECU response CAN id, e.g. 672")
    ap.add_argument("--from", dest="frm", default="0x2E00")
    ap.add_argument("--to", default="0x2F00")
    ap.add_argument("--delay", type=float, default=0.05)
    args = ap.parse_args()
    asyncio.run(scan(args.req, args.resp, int(args.frm, 0), int(args.to, 0), args.delay))


if __name__ == "__main__":
    main()
