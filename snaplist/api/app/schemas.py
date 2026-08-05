"""Pydantic models shared across the pipeline."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ItemSpecific(BaseModel):
    name: str
    value: str


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
