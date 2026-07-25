"""
Diagnostics API — the keystone between the Lovable phone app and the engine.

Architecture: THIN TRANSPORT, SMART SERVER.
  - The phone owns the BLE link to the dongle and just moves bytes.
  - This server owns the definitions, the security/legal gates, the audit log,
    and the AI. It tells the phone which UDS command to send, and interprets the
    bytes that come back. Secrets and policy never leave the server.

Run:  uvicorn api.main:app --reload
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from coding_engine.bitcoding import apply_bits, lock_state
from .models import (
    ApplyRequest, ApplyResponse, AssistantRequest, AssistantResponse,
    CodingFeature, CodingOption, DtcDecode, PreviewRequest, PreviewResponse,
)

app = FastAPI(title="Expert Car Check — Diagnostics API", version="0.1.0")

# Operations refused by policy, mirrored from coders.REFUSED_OPERATIONS.
REFUSED_OPERATIONS = {"key", "immobilizer"}


# --- dependencies (lazy so the app imports without heavy SDKs) ---------------
def get_store():
    from coding_engine.supabase_store import Store
    return Store()


# --- health ------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}


# --- DTC decode --------------------------------------------------------------
@app.get("/dtc/{code}", response_model=DtcDecode)
def decode_dtc(code: str, make: str | None = None, store=Depends(get_store)):
    row = store.decode_dtc(code, make)
    if not row:
        raise HTTPException(404, f"Unknown DTC {code}")
    return DtcDecode(**{k: row.get(k) for k in DtcDecode.model_fields})


# --- coding: list features for a vehicle's ECU (with lock states) ------------
@app.get("/ecu/{ecu_id}/coding", response_model=list[CodingFeature])
def list_coding(ecu_id: str, store=Depends(get_store)):
    feats = []
    for d in store.definitions_for_ecu(ecu_id):
        if d.get("operation") in REFUSED_OPERATIONS:
            continue  # never expose key/immobilizer ops to the app
        read_cmd = f"22{d['did']:04X}" if d.get("did") else None
        feats.append(CodingFeature(
            definition_id=d["id"], feature_key=d["feature_key"], label=d["label"],
            description=d.get("description"), kind=d["kind"], did=d.get("did"),
            options=[CodingOption(**o) for o in d.get("options", [])],
            lock=lock_state(d), risk=d.get("risk", "low"),
            legal_class=d.get("legal_class", "comfort"), read_command=read_cmd,
        ))
    return feats


# --- coding: preview (server computes new block from the phone's read) -------
@app.post("/coding/preview", response_model=PreviewResponse)
def preview(req: PreviewRequest, store=Depends(get_store)):
    d = store.definition(req.ecu_id, req.feature_key)
    block = bytes.fromhex(req.current_block_hex)
    blocked = _policy_reason(d, allow_high_risk=False)

    option = next((o for o in d["options"] if o["label"] == req.option_label), None)
    if option is None:
        raise HTTPException(400, f"Unknown option '{req.option_label}'")

    new_block = apply_bits(block, d["byte_offset"], d.get("bit_offset"),
                           d["bit_length"], int(option["raw"]))
    write_cmd = None
    if d.get("did") and blocked is None:
        write_cmd = f"2E{d['did']:04X}{new_block.hex().upper()}"

    return PreviewResponse(
        changed=new_block != block, new_block_hex=new_block.hex().upper(),
        write_command=write_cmd,
        explanation=f"{d['label']} → {req.option_label}. {d.get('description') or ''}".strip(),
        lock=lock_state(d), risk=d.get("risk", "low"), blocked_reason=blocked,
    )


# --- coding: apply (server enforces gates + writes the audit log) ------------
@app.post("/coding/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest, store=Depends(get_store)):
    d = store.definition(req.ecu_id, req.feature_key)
    blocked = _policy_reason(d, allow_high_risk=req.allow_high_risk)
    if blocked:
        return ApplyResponse(result="blocked", blocked_reason=blocked)
    if not req.confirm:
        return ApplyResponse(result="blocked", blocked_reason="confirm=false")

    # The phone has already transmitted new_block via BLE; we record the change
    # (previous bytes stored for byte-for-byte revert).
    row = store.record_change(
        vehicle_id=req.vehicle_id, user_id=req.user_id, ecu_id=req.ecu_id,
        definition_id=d["id"], vin="", previous=bytes.fromhex(req.previous_block_hex),
        new=bytes.fromhex(req.new_block_hex), chosen_option=req.option_label,
    )
    return ApplyResponse(result="applied", audit_id=row["id"])


# --- assistant (RAG): natural language -> a stored definition ----------------
@app.post("/assistant/resolve", response_model=AssistantResponse)
def assistant(req: AssistantRequest):
    from ai.rag import resolve
    result = resolve(req.request, req.ecu_ids)
    return AssistantResponse(**{k: result.get(k) for k in AssistantResponse.model_fields})


# --- policy (mirrors coders._policy_check) -----------------------------------
def _policy_reason(d: dict, *, allow_high_risk: bool) -> str | None:
    if d.get("operation") in REFUSED_OPERATIONS:
        return "Key/immobilizer operations are refused by policy."
    if d.get("legal_class") == "emissions":
        return "Emissions-related coding is blocked."
    if d.get("sfd_required"):
        return "SFD-locked — requires a licensed SFD token."
    if (d.get("risk") == "high" or d.get("legal_class") == "safety") and not allow_high_risk:
        return "High-risk/safety-critical — requires authorised workshop mode."
    return None
