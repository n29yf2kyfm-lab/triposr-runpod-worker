"""
BMW coding — FDL (function data list) coding.

Model: a feature lives in a control unit's coding block (NCD, derived from a CAFD
definition). Each feature is one or more bits/nibbles at a byte offset inside the
block that is read/written via a UDS DID. We:

  1. read the whole coding block (read_did),
  2. patch only the bits the feature owns (from the coding_definition row),
  3. write it back (write_did),
  4. record before/after in the audit log.

Chassis note: F-series = classic CAN; G/I-series = CAN-FD. The transport layer
already handles that from the platform profile, so this file is bus-agnostic.

This module APPLIES definitions; it does not contain them. The per-car CAFD-derived
definitions come from your licensed PSdZData ingest (see ingest/).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..uds_client import UdsClient
from ..supabase_store import Store


@dataclass
class CodingChange:
    feature_key: str
    label: str
    previous_block: bytes
    new_block: bytes
    chosen_option: str
    changed: bool


def _apply_bits(block: bytes, byte_offset: int, bit_offset: int | None,
                bit_length: int, raw_value: int) -> bytes:
    b = bytearray(block)
    if bit_offset is None:                       # whole-byte write
        b[byte_offset] = raw_value & 0xFF
        return bytes(b)
    mask = ((1 << bit_length) - 1) << bit_offset
    b[byte_offset] = (b[byte_offset] & ~mask) | ((raw_value << bit_offset) & mask)
    return bytes(b)


def _read_bits(block: bytes, byte_offset: int, bit_offset: int | None,
               bit_length: int) -> int:
    if bit_offset is None:
        return block[byte_offset]
    mask = (1 << bit_length) - 1
    return (block[byte_offset] >> bit_offset) & mask


def preview_feature(uds: UdsClient, store: Store, ecu_id: str, feature_key: str,
                    option_label: str) -> CodingChange:
    """Read current state and compute the new block WITHOUT writing (dry run)."""
    d = store.definition(ecu_id, feature_key)
    if d["kind"] != "fdl":
        raise ValueError(f"{feature_key} is not an FDL coding definition")

    option = next(o for o in d["options"] if o["label"] == option_label)
    block = uds.read_did(d["did"])
    new_block = _apply_bits(block, d["byte_offset"], d.get("bit_offset"),
                            d["bit_length"], int(option["raw"]))
    return CodingChange(
        feature_key=feature_key, label=d["label"],
        previous_block=block, new_block=new_block,
        chosen_option=option_label, changed=(new_block != block),
    )


def apply_feature(uds: UdsClient, store: Store, *, ecu_id: str, feature_key: str,
                  option_label: str, vin: str, vehicle_id=None, user_id=None,
                  confirm: bool = False) -> CodingChange:
    """
    Full guarded write:  security-gate check -> preview -> confirm -> write -> audit.
    """
    d = store.definition(ecu_id, feature_key)

    # legal / risk gates (see SAFETY.md)
    if d["legal_class"] == "emissions":
        raise PermissionError(f"{feature_key} is emissions-related; blocked by policy.")
    if d.get("sfd_required"):
        raise PermissionError(f"{feature_key} requires SFD; use a licensed SfdTokenProvider.")

    change = preview_feature(uds, store, ecu_id, feature_key, option_label)
    if not change.changed:
        return change
    if not confirm:
        raise RuntimeError("Refusing to write without confirm=True (preview only).")

    if d.get("security_level"):
        uds.unlock(d["security_level"], vin=vin, ecu_key=str(ecu_id))

    uds.extended_session()
    uds.write_did(d["did"], change.new_block)

    store.record_change(
        vehicle_id=vehicle_id, user_id=user_id, ecu_id=ecu_id,
        definition_id=d["id"], vin=vin,
        previous=change.previous_block, new=change.new_block,
        chosen_option=option_label,
    )
    return change


def revert(uds: UdsClient, store: Store, audit_row: dict, *, ecu_id: str,
           did: int, vin: str):
    """Byte-for-byte revert using the stored previous_value."""
    previous = bytes.fromhex(audit_row["previous_value"])
    uds.extended_session()
    uds.write_did(did, previous)
    store.record_change(
        vehicle_id=audit_row.get("vehicle_id"), user_id=audit_row.get("user_id"),
        ecu_id=ecu_id, definition_id=audit_row.get("definition_id"), vin=vin,
        previous=bytes.fromhex(audit_row["new_value"]), new=previous,
        chosen_option=audit_row.get("chosen_option", ""), result="reverted",
    )
