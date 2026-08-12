"""
Pure bit-coding helpers — no CAN/UDS/BLE dependencies.

Shared by the coders and the API (so the API can compute coding previews without
importing the whole protocol stack). Read/modify/write of a coding block.
"""
from __future__ import annotations


def apply_bits(block: bytes, byte_offset: int, bit_offset: int | None,
               bit_length: int, raw_value: int) -> bytes:
    b = bytearray(block)
    if bit_offset is None:                       # whole-byte write
        b[byte_offset] = raw_value & 0xFF
        return bytes(b)
    mask = ((1 << bit_length) - 1) << bit_offset
    b[byte_offset] = (b[byte_offset] & ~mask) | ((raw_value << bit_offset) & mask)
    return bytes(b)


def read_bits(block: bytes, byte_offset: int, bit_offset: int | None,
              bit_length: int) -> int:
    if bit_offset is None:
        return block[byte_offset]
    mask = (1 << bit_length) - 1
    return (block[byte_offset] >> bit_offset) & mask


def lock_state(definition: dict) -> str:
    """Map a coding_definition to the UI lock state: open | security | sfd."""
    if definition.get("sfd_required"):
        return "sfd"
    if definition.get("security_level"):
        return "security"
    return "open"
