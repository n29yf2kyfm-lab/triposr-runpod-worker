# Bluetooth dongle layer — connect, diagnose, reverse-engineer

The dongle is how the phone reaches the car's OBD port, and — with the right chip —
your **reverse-engineering capture tool**.

## The hardware reality (decide this first)

| Dongle chip | Coding | RE / CAN sniffing | iOS | Notes |
|-------------|--------|-------------------|-----|-------|
| Cheap **ELM327** BLE clone | basic OBD only | ❌ unreliable | some | fine for read codes / live data |
| **STN11xx** (OBDLink MX+/CX) | ✅ | ✅ (`STM`/`STMA` monitor, CAN filters) | ✅ | **use this for coding + RE** |
| Dedicated CAN (Macchina/CANtact) | ✅ raw | ✅ best | ✗ (USB) | laptop RE only |

**For reverse engineering and coding, get an STN-based BLE dongle (OBDLink MX+).** A stock
ELM327 can only be a polite OBD tester; it can't watch the bus properly.

## The iOS constraint (this shapes the whole app)

- **iOS Safari has no Web Bluetooth.** A pure Lovable web app **cannot** talk to a BLE dongle on
  iPhone. There is no workaround in the browser.
- **Solution:** wrap the Lovable web app with **Capacitor** and use
  `@capacitor-community/bluetooth-le` (native BLE on iOS *and* Android). Same TypeScript, one
  native shell. → `app/bluetooth/obdBle.ts` targets Capacitor, with a Web Bluetooth fallback so
  you can still develop/test on Android/desktop Chrome.
- BLE only (not Bluetooth Classic/SPP) — iOS never exposes SPP to apps.

## Two code paths

```
┌─ Phone app (Lovable + Capacitor) ─────────────┐    ┌─ RE / dev laptop (Python) ─────────┐
│  app/bluetooth/obdBle.ts                       │    │  coding_engine/ble/ble_dongle.py    │
│   Capacitor BLE  (iOS + Android)               │    │   bleak BLE                          │
│   Web Bluetooth  (Android/desktop fallback)    │    │  coding_engine/ble/elm327.py        │
│   → ELM327/STN AT protocol                     │    │   ELM327/STN AT protocol            │
│   → diagnostics + coding via the API           │    │  re_tools/can_sniffer.py  ← capture │
└────────────────────────────────────────────────┘    │  re_tools/uds_scan.py     ← DID sweep│
                                                        └─────────────────────────────────────┘
```

## The reverse-engineering workflow (with the dongle)

1. **Capture** — `re_tools/can_sniffer.py` puts an STN dongle in monitor mode and logs every
   frame (candump/CSV) with timestamps.
2. **Provoke** — toggle a feature with the OEM/engineering tool (or press a button).
3. **Diff** — compare captures before/after; the bytes that changed are your signal.
4. **Enumerate** — `re_tools/uds_scan.py` sweeps ReadDataByIdentifier (0x22) on an ECU to find
   which DIDs hold coding blocks (read-only; safe).
5. **Encode** — record the mapping as a `coding_definition` row (via `ingest/`), mark
   `verified=true` once you've confirmed it on a car you own.

> RE is done on **your own vehicle**. Respect the security/legal boundaries in `SAFETY.md`;
> the scanners here are read-only and do not attempt security-access bypass.
