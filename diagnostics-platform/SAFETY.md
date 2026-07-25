# SAFETY & LEGAL — read before writing to any vehicle

Coding and diagnostics are legitimate and widely practised, but **writes are not undoable in
the way software is.** This document is the contract the whole engine is built to honour.

## Hard rules enforced in code
1. **Never write a value the AI generated.** Coding values come *only* from a stored
   `coding_definition` row. `ai/rag.py` returns guidance + a definition ID; the engine
   re-reads the value from the DB before writing. (`coding_engine/supabase_store.py`)
2. **Read-before-write, always.** Every write first reads the current coding block and stores
   it in `coding_audit.previous_value`, so any change can be reverted byte-for-byte.
3. **Preview + explicit confirm.** `write_*` functions require `confirm=True` and emit a
   human-readable diff first. `--dry-run` performs the full flow without transmitting.
4. **Audit everything.** Every write appends to `coding_audit` (who, when, VIN, ECU, before,
   after, definition id). No silent changes.
5. **Refuse what you can't reverse.** Module flashing (UDS 0x34/0x36/0x37) and writes to
   safety ECUs (airbag/SRS, ABS actuator programming) are **gated behind an explicit
   `allow_high_risk` capability** and are out of scope for the consumer app.

## Security gates you must respect (not bypass)
- **Security Access (UDS 0x27):** the seed→key algorithm is the manufacturer's. Supply your
  own **licensed** algorithm/token via the `security.py` plug-in. This repo ships **no**
  algorithms.
- **SFD (VW Group 2020+):** coding is locked behind online authorisation with VW's servers.
  Provide a **licensed** `SfdTokenProvider`. Do not attempt to defeat it.
- **Secure Gateway (Stellantis, newer BMW/Toyota):** in the US requires NASTF registration.
  Configure valid credentials; don't circumvent.

## Legal
- **Emissions-related coding is illegal** in many jurisdictions (removing DPF/EGR/cat
  monitoring). The engine tags such definitions `legal_class = 'emissions'` and blocks them
  unless `allow_emissions=True` is explicitly set for an off-road/authorised context.
- **Proprietary formats** (e.g. Ross-Tech compiled `.CLB`, encrypted PSdZData) must not be
  decrypted or redistributed. Ingest only plaintext/licensed sources you are entitled to use.
- Reverse engineering for **interoperability** is permitted in many jurisdictions but varies —
  confirm for your market.

If a request would violate any of the above, the correct behaviour is to **refuse and explain**,
not to work around it.
