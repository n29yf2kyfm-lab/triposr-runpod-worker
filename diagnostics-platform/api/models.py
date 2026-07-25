"""Pydantic request/response models for the diagnostics API."""
from __future__ import annotations

from pydantic import BaseModel


# --- DTC ---------------------------------------------------------------------
class DtcDecode(BaseModel):
    code: str
    title: str
    plain_english: str | None = None
    severity: str | None = None
    typical_fix: str | None = None
    est_cost_low: int | None = None
    est_cost_high: int | None = None


# --- coding list -------------------------------------------------------------
class CodingOption(BaseModel):
    label: str
    raw: int


class CodingFeature(BaseModel):
    definition_id: str
    feature_key: str
    label: str
    description: str | None = None
    kind: str
    did: int | None = None
    options: list[CodingOption] = []
    lock: str                      # 'open' | 'security' | 'sfd'
    risk: str
    legal_class: str
    read_command: str | None = None  # hex UDS the phone should send to read the block


# --- preview / apply (thin-transport model) ----------------------------------
class PreviewRequest(BaseModel):
    vehicle_id: str | None = None
    ecu_id: str
    feature_key: str
    option_label: str
    current_block_hex: str          # phone read this via BLE and sends it up


class PreviewResponse(BaseModel):
    changed: bool
    new_block_hex: str
    write_command: str | None = None  # hex UDS the phone should send to write
    explanation: str
    lock: str
    risk: str
    blocked_reason: str | None = None


class ApplyRequest(BaseModel):
    vehicle_id: str | None = None
    user_id: str | None = None
    ecu_id: str
    feature_key: str
    option_label: str
    previous_block_hex: str
    new_block_hex: str
    confirm: bool = False
    allow_high_risk: bool = False


class ApplyResponse(BaseModel):
    result: str                     # 'applied' | 'blocked'
    audit_id: str | None = None
    blocked_reason: str | None = None


# --- assistant (RAG) ---------------------------------------------------------
class AssistantRequest(BaseModel):
    request: str
    ecu_ids: list[str]


class AssistantResponse(BaseModel):
    definition_id: str | None = None
    option_label: str | None = None
    explanation: str
    risk: str
    refuse_reason: str | None = None


# --- onboarding (from an in-app scan) ----------------------------------------
class OnboardModule(BaseModel):
    respId: int
    name: str
    part: str | None = None
    sw: str | None = None


class OnboardRequest(BaseModel):
    vin: str | None = None
    make: str | None = None
    bus: str = "can"
    modules: list[OnboardModule] = []


class OnboardResponse(BaseModel):
    platform_id: str
    make: str
    family: str | None = None
    ecu_count: int
