# API layer — connects the Lovable app to the engine

**Thin transport, smart server.** The phone owns the BLE dongle link and only moves
bytes; this server owns the definitions, the security/legal gates, the audit log, and
the AI. Secrets and policy never reach the client.

## Why this split
- The car is with the **phone**, not the server — so the phone must be the transport.
- But coding **policy** (what's allowed, SFD/security gates, key/immobilizer refusal) and
  the **audit log** must be server-authoritative and un-bypassable.
- So the server returns the *exact UDS command* to send and interprets the response; the
  phone executes it over BLE. A tampered client still can't get a blocked write applied,
  because the audit + gate live on the server.

## Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | liveness |
| GET  | `/dtc/{code}` | decode a fault code (plain English, cost, fix) |
| GET  | `/ecu/{ecu_id}/coding` | list codeable features **with lock states** (open/security/sfd) + the read command |
| POST | `/coding/preview` | server computes the new coding block from the phone's read; returns the write command + gate status |
| POST | `/coding/apply` | server enforces gates and records the reversible audit entry |
| POST | `/assistant/resolve` | RAG: natural language → a stored definition (values from DB, never invented) |

## The coding round-trip (phone ⇄ server)
```
1. GET /ecu/{id}/coding           → features + lock states + read_command (e.g. "223000")
2. phone: BLE send read_command   → current_block_hex
3. POST /coding/preview {block}   → new_block_hex + write_command (or blocked_reason)
4. phone: BLE send write_command  → ok
5. POST /coding/apply {before,after,confirm} → audit_id (reversible)
```
Key/immobilizer definitions are never returned by `/coding`, and every write endpoint
re-checks the policy gates server-side.

## Deploy options
- **FastAPI** (`uvicorn api.main:app`) on any host, or
- Port the same handlers to a **Supabase Edge Function** to keep everything in one place —
  the logic is small and DB-centric.

Run locally:
```bash
pip install -r api/requirements.txt -r coding_engine/requirements.txt
uvicorn api.main:app --reload
# http://127.0.0.1:8000/docs
```
