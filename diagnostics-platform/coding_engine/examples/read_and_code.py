"""
End-to-end demo: connect, read a coding block, preview a change, (optionally) write.

Run WITHOUT a car using the ELM327 emulator or a virtual CAN bus:

    # option A: virtual SocketCAN (Linux)
    sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
    python -m coding_engine.examples.read_and_code --dry-run --channel vcan0 --interface socketcan

    # option B: against the ELM327-emulator (pip install ELM327-emulator; run `elm`)
    python -m coding_engine.examples.read_and_code --dry-run --interface slcan --channel /dev/ttyS10

`--dry-run` performs the entire flow (read + preview + audit-preview) but never
transmits a write. Drop it (and pass --confirm) only on a car you own/are authorised
to service.
"""
from __future__ import annotations

import argparse

from coding_engine import (PlatformProfile, open_bus, open_isotp, UdsClient, Store)
from coding_engine.platforms import bmw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interface", default="virtual")
    ap.add_argument("--channel", default="vcan0")
    ap.add_argument("--platform-id", help="Supabase platform id")
    ap.add_argument("--ecu-key", default="FEM_BODY")
    ap.add_argument("--feature", default="mirror_fold_on_lock")
    ap.add_argument("--option", default="On")
    ap.add_argument("--vin", default="WBADEMO000000000")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    store = Store()

    # In a real run these come from Supabase; here we hardcode a G-series (CAN-FD)
    # body module so the demo is self-contained.
    platform_row = {"make": "BMW", "family": "G-series", "bus": "canfd",
                    "can_bitrate": 500_000, "canfd_data_bitrate": 2_000_000}
    ecu_row = {"req_id": 0x6F1, "resp_id": 0x672, "addressing": "physical",
               "id": args.ecu_key}

    profile = PlatformProfile(
        make=platform_row["make"], family=platform_row["family"], bus=platform_row["bus"],
        can_bitrate=platform_row["can_bitrate"], canfd_data_bitrate=platform_row["canfd_data_bitrate"],
        req_id=ecu_row["req_id"], resp_id=ecu_row["resp_id"],
    )
    print(f"→ {profile.make} {profile.family} on "
          f"{'CAN-FD' if profile.is_fd else 'classic CAN'} "
          f"({profile.can_bitrate}"
          f"{'/'+str(profile.canfd_data_bitrate) if profile.is_fd else ''} bps)")

    bus = open_bus(profile, channel=args.channel, interface=args.interface)
    stack = open_isotp(bus, profile)

    with UdsClient(stack) as uds:
        change = bmw.preview_feature(uds, store, ecu_row["id"], args.feature, args.option)
        print(f"\nFeature : {change.label}  → {change.chosen_option}")
        print(f"Before  : {change.previous_block.hex(' ')}")
        print(f"After   : {change.new_block.hex(' ')}")
        print(f"Changed : {change.changed}")

        if args.dry_run:
            print("\n[dry-run] No write transmitted.")
            return
        bmw.apply_feature(uds, store, ecu_id=ecu_row["id"], feature_key=args.feature,
                          option_label=args.option, vin=args.vin, confirm=args.confirm)
        print("\n✓ Applied and logged to coding_audit (reversible).")


if __name__ == "__main__":
    main()
