"""
French manufacturers — Renault/Dacia (CLIP-class) and PSA Peugeot/Citroën/DS
(DiagBox-class).

Engineering tools: Renault CLIP ("Can Clip"); PSA DiagBox / Lexia.
Aftermarket:       DDT4All (CAN + KWP2000).
Protocols by era:
  - older: KWP2000 (ISO 14230) on K-Line — needs a K-Line backend (see PROTOCOLS.md)
  - newer: UDS over CAN; some late PSA/Stellantis add a secure gateway

Both marques use the shared bit-coding flow. `MARQUE` selects addressing/security
profiles stored per-platform in the DB; there is no divergent write path here.
"""
from __future__ import annotations

from . import coders
from .coders import CodingChange   # re-export

RENAULT = "renault"
PSA = "psa"

PROTOCOL_NOTES = {
    "renault_modern": "UDS over CAN (CLIP-class coverage).",
    "psa_modern": "UDS over CAN; secure gateway on newer Stellantis — configure credentials.",
    "legacy": "KWP2000 on K-Line — requires a K-Line backend behind UdsClient.",
}

preview = coders.preview
apply = coders.apply
run_service_routine = coders.run_service_routine
