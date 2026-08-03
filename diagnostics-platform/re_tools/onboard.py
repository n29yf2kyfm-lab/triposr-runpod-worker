#!/usr/bin/env python3
"""
Auto-onboard a vehicle from a single scan.

Runs module discovery, decodes the VIN to identify the make, then creates the
`platform` row + all discovered `ecu` rows in Supabase. Turns "unknown car" into a
populated, codeable profile in one step.

    python -m re_tools.onboard --sim --json          # preview, no hardware/DB
    python -m re_tools.onboard --wifi --to-supabase  # real scan → Supabase

Bus (CAN vs CAN-FD) can't be reliably detected via a basic ELM327, so it defaults
to classic CAN; pass --bus canfd for G/I-series BMW, MQB-Evo/MEB VAG, etc.
Read-only on the vehicle (0x3E/0x22).
"""
from __future__ import annotations

import argparse
import json

from .module_discovery import (ELM327, WIFI_IP, WIFI_PORT, discover, read_idents,
                               to_ecu_rows)

# VIN World-Manufacturer-Identifier prefixes → make/family. First 3 VIN chars.
WMI = {
    "WVW": ("VAG", "VW"), "WV1": ("VAG", "VW"), "WV2": ("VAG", "VW"),
    "WAU": ("VAG", "Audi"), "WA1": ("VAG", "Audi"), "TRU": ("VAG", "Audi"),
    "VSS": ("VAG", "SEAT"), "TMB": ("VAG", "Skoda"),
    "WBA": ("BMW", "BMW"), "WBS": ("BMW", "BMW-M"), "WBY": ("BMW", "BMW-i"),
    "4US": ("BMW", "BMW"), "5UX": ("BMW", "BMW-X"),
    "JTD": ("Toyota", "Toyota"), "JTM": ("Toyota", "Toyota"), "JTH": ("Toyota", "Lexus"),
    "SB1": ("Toyota", "Toyota"), "VF1": ("Renault", "Renault"), "VF6": ("Renault", "Renault"),
    "VF3": ("PSA", "Peugeot"), "VF7": ("PSA", "Citroen"),
    "WF0": ("Ford", "Ford"), "WDD": ("Mercedes", "Mercedes"), "W1K": ("Mercedes", "Mercedes"),
}

# VIN 10th char → model year (1980-2039 cycle; enough for the recent range).
YEAR_CODE = {c: y for y, c in enumerate(
    "ABCDEFGHJKLMNPRSTVWXY123456789", start=2010)}


def decode_vin(vin: str) -> dict:
    vin = (vin or "").upper().strip()
    make, family = WMI.get(vin[:3], (None, None))
    year = YEAR_CODE.get(vin[9]) if len(vin) >= 10 else None
    return {"vin": vin or None, "make": make, "family": family, "year": year}


def find_vin(found: dict) -> str | None:
    for data in found.values():
        if data.get("F190"):
            return data["F190"]
    return None


def build_platform(vinfo: dict, bus: str) -> dict:
    return {
        "make": vinfo["make"] or "Unknown",
        "family": vinfo["family"] or "scanned",
        "year_from": vinfo["year"],
        "bus": bus,
        "protocol": "uds",
        "notes": f"Auto-onboarded from scan. VIN {vinfo.get('vin') or 'n/a'}.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--wifi", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--bus", default="can", choices=["can", "canfd"])
    ap.add_argument("--to-supabase", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    elm, sim = None, args.sim
    if not sim:
        try:
            elm = ELM327(ip=WIFI_IP, port=WIFI_PORT) if args.wifi else ELM327(serial_port=args.port)
            elm.init_obd()
        except Exception as e:
            print(f"  adapter unreachable ({e}) → simulation\n"); sim = True

    found = read_idents(discover(sim=sim, elm=elm), sim=sim, elm=elm)
    vinfo = decode_vin(find_vin(found))
    platform = build_platform(vinfo, args.bus)

    print(f"\n  VIN     : {vinfo['vin'] or 'not read'}")
    print(f"  Make    : {platform['make']} ({platform['family']})"
          f"{'  year ' + str(vinfo['year']) if vinfo['year'] else ''}")
    print(f"  Bus     : {platform['bus']}")
    print(f"  Modules : {len(found)}")

    if args.to_supabase:
        from coding_engine.supabase_store import get_client
        db = get_client()
        prow = db.table("platform").insert(platform).execute().data[0]
        ecus = to_ecu_rows(found, prow["id"])
        db.table("ecu").upsert(ecus, on_conflict="platform_id,key").execute()
        print(f"\n  ✓ created platform {prow['id']} + {len(ecus)} ECUs in Supabase")
    elif args.json:
        print(json.dumps({"platform": platform,
                          "ecus": to_ecu_rows(found, "NEW_PLATFORM_ID")}, indent=2))


if __name__ == "__main__":
    main()
