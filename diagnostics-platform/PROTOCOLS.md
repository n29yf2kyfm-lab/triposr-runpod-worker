# Diagnostic protocols by manufacturer — why coding is separated per brand

Each manufacturer family speaks a different diagnostic "language," on a different physical
bus, with its own engineering tool. That's why `coding_engine/platforms/` has one module per
family and the `platform` row carries a `protocol` + `bus` the transport layer reads.

| Family | OEM / engineering tool | Aftermarket | Protocol(s) | Physical bus |
|--------|------------------------|-------------|-------------|--------------|
| **VAG** (VW/Audi/Škoda/SEAT/Cupra) | ODIS, ODIS-E | VCDS, OBDeleven | KWP1281 → KWP2000 (ISO 14230) → **UDS** (ISO 14229) | K-Line → CAN → **CAN-FD** (MQB-Evo/MEB) |
| **BMW** / Mini / RR | ISTA, E-Sys (EDIABAS/INPA/NCS) | BimmerCode, Carly | DS2 → KWP/**UDS**, **DoIP** (Ethernet) | K-Line/DS2 → CAN → Ethernet; CAN-FD on G/I |
| **Toyota** / Lexus / Scion | Techstream (GTS) | — | ISO 9141 (K-Line) · KWP2000 · J1850 · **CAN ISO 15765** | K-Line (pre-~2008) → CAN |
| **Renault** / Dacia | CLIP (Can Clip) | DDT4All | KWP2000 → **UDS** | K-Line → CAN |
| **PSA** (Peugeot/Citroën/DS) | DiagBox, Lexia | DDT4All | KWP2000 → **UDS** | K-Line → CAN; secure gateway on new |
| **Mercedes** | Xentry/DAS (Vediamo, DTS Monaco) | — | KWP → **UDS** | K-Line → CAN → CAN-FD/DoIP |

## What this means for the engine

- **Modern cars (≈2008+): UDS over CAN / CAN-FD.** Fully handled by `transport.py` + `uds_client.py`.
  This covers the vast majority of coding work and all the newer BMW/VAG/Toyota/French cars.
- **Older cars: K-Line (ISO 9141 / KWP2000).** A *different physical layer* — not CAN. It needs a
  K-Line-capable interface (many ELM327 support it via AT commands; `python-can` does **not**).
  `transport.py` records the protocol so the app can pick the right interface, and a K-Line
  backend can be added behind the same `UdsClient`-style API (KWP2000 is UDS's ancestor, so the
  service model maps closely). Marked as a clean extension point, not faked.

## Per-family modules
- `platforms/bmw.py`   — FDL coding (UDS/DoIP)
- `platforms/vag.py`   — long-coding + adaptations (UDS; SFD-gated on 2020+)
- `platforms/toyota.py` — customer settings / coding (UDS on CAN; K-Line note for pre-2008)
- `platforms/french.py` — Renault (CLIP-class) + PSA (DiagBox-class): KWP2000 → UDS

The **coding mechanics are shared** (read block → patch bits → write, all in one place); what
differs per family is the **transport, addressing, security, and the definitions** — which is
exactly what the `platform`/`ecu`/`coding_definition` rows and the security provider carry.
