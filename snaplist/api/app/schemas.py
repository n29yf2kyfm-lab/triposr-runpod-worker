"""Pydantic models shared across the pipeline."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ItemSpecific(BaseModel):
    name: str
    value: str


def coerce_text(value: object, default: str = "") -> str:
    """
    Model output -> a string field, falling back to `default`.

    `data.get("brand", "")` is not enough: a JSON `null` returns None, which a
    required `str` field rejects with a 500. Numbers are accepted and stringified.
    """
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return default


def coerce_text_list(raw: object) -> list[str]:
    """Model output -> a list of non-empty strings (a bare string becomes one item)."""
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    return [t for t in (coerce_text(v) for v in raw) if t]


def coerce_item_specifics(raw: object) -> list[ItemSpecific]:
    """
    Build ItemSpecifics from loosely-typed model output.

    An LLM asked for `[{"name": ..., "value": ...}]` will sometimes answer with a
    number (`"value": 64`), a list of values, a bool, or a missing value —
    constructing ItemSpecific directly from those raises ValidationError and
    turns the whole request into a 500, so everything is coerced to text here and
    anything unusable is skipped.
    """
    out: list[ItemSpecific] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        value = row.get("value")
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if v not in (None, ""))
        elif isinstance(value, bool):
            value = "Yes" if value else "No"
        value = "" if value is None else str(value).strip()
        if name and value:
            out.append(ItemSpecific(name=name, value=value))
    return out


class Identification(BaseModel):
    title_guess: str = Field(..., description="Short human name for the item")
    brand: str = ""
    model: str = ""
    category: str = ""
    condition: str = "Used"
    color: str = ""
    material: str = ""
    attributes: list[ItemSpecific] = []
    confidence: float = Field(0.0, ge=0, le=1)
    notes: str = ""
    image_id: str = ""  # set by the identify endpoint after the upload is stored
    source: str = "mock"  # "anthropic" | "mock"


class PriceComp(BaseModel):
    title: str
    price: float
    currency: str = "USD"
    source: str = ""
    url: str = ""


class Pricing(BaseModel):
    suggested_price: float
    currency: str = "USD"
    low: float = 0.0
    high: float = 0.0
    comps: list[PriceComp] = []
    rationale: str = ""
    source: str = "mock"


class Listing(BaseModel):
    title: str  # <= 80 chars for eBay
    subtitle: str = ""
    description_html: str
    bullet_points: list[str] = []
    item_specifics: list[ItemSpecific] = []
    keywords: list[str] = []
    category_id: str = ""
    source: str = "mock"


class VideoStoryboardShot(BaseModel):
    seconds: float
    visual: str
    caption: str


class PromoVideo(BaseModel):
    status: str  # "ready" | "storyboard_only" | "processing"
    video_url: str = ""
    thumbnail_url: str = ""
    duration_s: float = 0.0
    hook: str = ""
    caption: str = ""
    hashtags: list[str] = []
    storyboard: list[VideoStoryboardShot] = []
    source: str = "mock"


# ---- request bodies ----


class PriceRequest(BaseModel):
    identification: Identification


class ListingRequest(BaseModel):
    identification: Identification
    pricing: Pricing


class VideoRequest(BaseModel):
    identification: Identification
    listing: Listing
    image_id: str = ""


class PublishRequest(BaseModel):
    listing: Listing
    pricing: Pricing
    image_id: str = ""


class PublishResult(BaseModel):
    status: str  # "published" | "draft" | "error"
    listing_id: str = ""
    view_url: str = ""
    environment: str = "sandbox"
    message: str = ""
    live: bool = False
