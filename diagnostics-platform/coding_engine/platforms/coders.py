"""
Shared coding mechanics used by every manufacturer module.

The bit-patch read/modify/write is identical across brands; what differs is the
transport, addressing, security and the definitions (all carried by the DB rows +
security provider). This module also enforces the platform-wide POLICY GATES so
every brand inherits them:

  - emissions coding                → refused
  - key / immobilizer operations    → refused (see SAFETY.md; theft vector)
  - high-risk / safety-critical ops → require allow_high_risk=True + security provider
  - every write                     → read-before-write + audit (reversible)
"""
from __future__ import annotations

from dataclasses import dataclass

from ..uds_client import UdsClient
from ..supabase_store import Store

REFUSED_OPERATIONS = {"key", "immobilizer"}


@dataclass
class CodingChange:
    feature_key: str
    label: str
    previous_block: bytes
    new_block: bytes
    chosen_option: str
    changed: bool


def apply_bits(block: bytes, byte_offset: int, bit_offset: int | None,
               bit_length: int, raw_value: int) -> bytes:
    b = bytearray(block)
    if bit_offset is None:
        b[byte_offset] = raw_value & 0xFF
        return bytes(b)
    mask = ((1 << bit_length) - 1) << bit_offset
    b[byte_offset] = (b[byte_offset] & ~mask) | ((raw_value << bit_offset) & mask)
    return bytes(b)


def _policy_check(d: dict, *, allow_high_risk: bool, allow_emissions: bool):
    op = d.get("operation", "coding")
    if op in REFUSED_OPERATIONS:
        raise PermissionError(
            f"Operation '{op}' (key/immobilizer) is refused by policy. Use identity-"
            f"verified, OEM-authorised locksmith tooling — not this framework."
        )
    if d.get("legal_class") == "emissions" and not allow_emissions:
        raise PermissionError(f"{d['feature_key']} is emissions-related; blocked by policy.")
    if d.get("sfd_required"):
        raise PermissionError(f"{d['feature_key']} requires SFD; use a licensed SfdTokenProvider.")
    if (d.get("risk") == "high" or d.get("legal_class") == "safety") and not allow_high_risk:
        raise PermissionError(
            f"{d['feature_key']} is high-risk/safety-critical (can brick a module). "
            f"Pass allow_high_risk=True only for an authorised workshop context, with a "
            f"licensed security provider configured."
        )


def preview(uds: UdsClient, store: Store, ecu_id: str, feature_key: str,
            option_label: str) -> CodingChange:
    """Read current state and compute the new block WITHOUT writing."""
    d = store.definition(ecu_id, feature_key)
    if d["kind"] not in ("fdl", "long_coding"):
        raise ValueError(f"{feature_key} is not a bit-coding definition (kind={d['kind']})")
    option = next(o for o in d["options"] if o["label"] == option_label)
    block = uds.read_did(d["did"])
    new_block = apply_bits(block, d["byte_offset"], d.get("bit_offset"),
                           d["bit_length"], int(option["raw"]))
    return CodingChange(feature_key, d["label"], block, new_block,
                        option_label, new_block != block)


def apply(uds: UdsClient, store: Store, *, ecu_id: str, feature_key: str,
          option_label: str, vin: str, vehicle_id=None, user_id=None,
          confirm: bool = False, allow_high_risk: bool = False,
          allow_emissions: bool = False) -> CodingChange:
    """Guarded write: policy gates → preview → confirm → (unlock) → write → audit."""
    d = store.definition(ecu_id, feature_key)
    _policy_check(d, allow_high_risk=allow_high_risk, allow_emissions=allow_emissions)

    change = preview(uds, store, ecu_id, feature_key, option_label)
    if not change.changed:
        return change
    if not confirm:
        raise RuntimeError("Refusing to write without confirm=True (preview only).")

    uds.extended_session()
    if d.get("security_level"):
        uds.unlock(d["security_level"], vin=vin, ecu_key=str(ecu_id))
    uds.write_did(d["did"], change.new_block)

    store.record_change(
        vehicle_id=vehicle_id, user_id=user_id, ecu_id=ecu_id,
        definition_id=d["id"], vin=vin, previous=change.previous_block,
        new=change.new_block, chosen_option=option_label,
    )
    return change


def run_service_routine(uds: UdsClient, store: Store, *, ecu_id: str, feature_key: str,
                        vin: str, allow_high_risk: bool = False, confirm: bool = False):
    """
    High-risk service routine via RoutineControl (0x31): ABS pump bleed/replace,
    steering-lock (ESL/ELV) initialisation, calibrations. Legitimate REPAIR ops —
    gated hard because they can immobilise or brick a car.
    """
    d = store.definition(ecu_id, feature_key)
    _policy_check(d, allow_high_risk=allow_high_risk, allow_emissions=False)
    if d["kind"] != "routine":
        raise ValueError(f"{feature_key} is not a service routine (kind={d['kind']})")
    if not allow_high_risk:
        raise PermissionError("Service routines require allow_high_risk=True (authorised workshop).")
    if not confirm:
        raise RuntimeError("Refusing to run without confirm=True.")

    uds.extended_session()
    if d.get("security_level"):
        uds.unlock(d["security_level"], vin=vin, ecu_key=str(ecu_id))
    uds.routine_start(d["routine_id"])
    store.record_change(
        vehicle_id=None, user_id=None, ecu_id=ecu_id,
        definition_id=d["id"], vin=vin, previous=b"", new=b"",
        chosen_option=d["label"], note="service routine executed",
    )
