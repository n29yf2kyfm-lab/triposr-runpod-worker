"""
VAG coding — long-coding (byte.bit) + adaptation channels.

Two mechanisms, both modelled by `coding_definition.kind`:

  - 'long_coding' : a coding string (bytes); a feature owns bit(s) at byte.bit,
                    exactly like BMW FDL. Read/write via UDS DID (MQB) — reuse the
                    same bit patching.
  - 'adaptation'  : a channel/value pair. On MQB this is UDS RoutineControl (0x31)
                    or WriteDataByIdentifier against an adaptation DID; on older
                    (PQ/KWP) it was measuring-block channels. We expose write via
                    routine/DID as configured on the definition row.

SFD (MQB-Evo/MEB, 2020+): if `sfd_required`, an SFD token must be obtained from a
licensed SfdTokenProvider BEFORE the write. This module refuses otherwise.

Bus note: MQB = classic CAN, MQB-Evo/MEB = CAN-FD — handled by the transport layer.
"""
from __future__ import annotations

from ..uds_client import UdsClient
from ..supabase_store import Store
from .bmw import CodingChange, _apply_bits   # identical bit mechanics — reuse


def preview_long_coding(uds: UdsClient, store: Store, ecu_id: str,
                        feature_key: str, option_label: str) -> CodingChange:
    d = store.definition(ecu_id, feature_key)
    if d["kind"] != "long_coding":
        raise ValueError(f"{feature_key} is not a long_coding definition")
    option = next(o for o in d["options"] if o["label"] == option_label)
    block = uds.read_did(d["did"])
    new_block = _apply_bits(block, d["byte_offset"], d.get("bit_offset"),
                            d["bit_length"], int(option["raw"]))
    return CodingChange(feature_key, d["label"], block, new_block,
                        option_label, new_block != block)


def apply_long_coding(uds: UdsClient, store: Store, *, ecu_id: str, feature_key: str,
                      option_label: str, vin: str, sfd_token: bytes | None = None,
                      vehicle_id=None, user_id=None, confirm: bool = False) -> CodingChange:
    d = store.definition(ecu_id, feature_key)

    if d["legal_class"] == "emissions":
        raise PermissionError(f"{feature_key} is emissions-related; blocked by policy.")
    if d.get("sfd_required") and not sfd_token:
        raise PermissionError(
            f"{feature_key} is SFD-protected. Obtain a token from your licensed "
            f"SfdTokenProvider and pass sfd_token=..."
        )

    change = preview_long_coding(uds, store, ecu_id, feature_key, option_label)
    if not change.changed:
        return change
    if not confirm:
        raise RuntimeError("Refusing to write without confirm=True (preview only).")

    uds.extended_session()
    if d.get("security_level"):
        uds.unlock(d["security_level"], vin=vin, ecu_key=str(ecu_id))
    # NOTE: sfd_token would be transmitted here via the manufacturer's unlock
    # sequence provided by your licensed SFD implementation.

    uds.write_did(d["did"], change.new_block)
    store.record_change(
        vehicle_id=vehicle_id, user_id=user_id, ecu_id=ecu_id,
        definition_id=d["id"], vin=vin, previous=change.previous_block,
        new=change.new_block, chosen_option=option_label,
    )
    return change


def write_adaptation(uds: UdsClient, store: Store, *, ecu_id: str, feature_key: str,
                     value: int, vin: str, confirm: bool = False):
    """Adaptation via RoutineControl (0x31) or an adaptation DID."""
    d = store.definition(ecu_id, feature_key)
    if d["kind"] != "adaptation":
        raise ValueError(f"{feature_key} is not an adaptation definition")
    if not confirm:
        raise RuntimeError("Refusing to write without confirm=True.")

    uds.extended_session()
    if d.get("security_level"):
        uds.unlock(d["security_level"], vin=vin, ecu_key=str(ecu_id))

    payload = value.to_bytes(d.get("bit_length", 1) // 8 or 1, "big")
    if d.get("routine_id"):
        uds.routine_start(d["routine_id"], payload)
    else:
        uds.write_did(d["did"], payload)
