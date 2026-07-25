"""
Toyota / Lexus / Scion — customer settings & coding.

Engineering tool: Techstream (GTS). Protocols by era:
  - pre-~2008: ISO 9141 / KWP2000 on the K-Line (needs a K-Line interface — see PROTOCOLS.md)
  - ~2008+   : UDS over CAN (ISO 15765). Handled by the standard transport + UdsClient.

Most consumer-facing Toyota "coding" is *customer settings* (auto-lock behaviour,
light timers, beep volume) exposed as coding blocks / adaptations — mapped to
coding_definition rows just like the other brands. Coding mechanics are shared.
"""
from __future__ import annotations

from . import coders
from .coders import CodingChange   # re-export for callers

PROTOCOL_NOTES = {
    "modern": "UDS over CAN (ISO 15765) — fully supported.",
    "legacy": "ISO 9141 / KWP2000 on K-Line — requires a K-Line backend behind UdsClient.",
}

# Toyota coding is the shared bit-coding flow; no brand-specific write quirks at
# this layer (session handling lives in UdsClient; addressing in the ecu row).
preview = coders.preview
apply = coders.apply
run_service_routine = coders.run_service_routine
