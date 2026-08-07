"""
SnapList API — photo -> eBay listing -> promo video.

Every step is its own endpoint so the frontend can show/let-you-edit results
between stages (identification is the one you always want a human to confirm).
Runs fully on mock data with no keys; goes live as you add them.
"""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import get_settings
from .providers import ebay, listing, pricing, video
from .providers import vision
from .schemas import (
    Identification,
    Listing,
    ListingRequest,
    PriceRequest,
    Pricing,
    PromoVideo,
    PublishRequest,
    PublishResult,
    VideoRequest,
)

app = FastAPI(title="SnapList API", version="0.1.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/health")
def health() -> dict:
    """Report which integrations are live vs running on demo data."""
    return {
        "ok": True,
        "integrations": {
            "ai_vision_and_copy": settings.ai_live,
            "pricing": settings.pricing_live,
            "video": settings.video_live,
            "ebay": settings.ebay_live,
            "ebay_env": settings.ebay_env,
        },
    }


@app.post("/api/identify", response_model=Identification)
async def identify(file: UploadFile = File(...)) -> Identification:
    data = await file.read()
    image_id = f"{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.jpg'}"
    (UPLOAD_DIR / image_id).write_bytes(data)
    result = await vision.identify(data, file.content_type or "image/jpeg", file.filename or "")
    result.image_id = image_id
    return result


@app.get("/api/image/{image_id}")
def get_image(image_id: str) -> FileResponse:
    path = UPLOAD_DIR / Path(image_id).name  # prevent traversal
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


@app.post("/api/price", response_model=Pricing)
async def price(req: PriceRequest) -> Pricing:
    return await pricing.price(req.identification)


@app.post("/api/listing", response_model=Listing)
async def make_listing(req: ListingRequest) -> Listing:
    return await listing.generate(req.identification, req.pricing)


@app.post("/api/video", response_model=PromoVideo)
async def make_video(req: VideoRequest) -> PromoVideo:
    return await video.generate(req.identification, req.listing, req.image_id)


@app.post("/api/publish", response_model=PublishResult)
async def publish(req: PublishRequest) -> PublishResult:
    """
    Publish to eBay. The stored photo is sent as bytes so it can be uploaded to
    eBay's own image hosting; a public self-hosted URL is only a fallback, since
    eBay has to fetch such images over the internet and cannot see localhost.
    """
    image_bytes: bytes | None = None
    media_type = "image/jpeg"
    fallback_url = ""

    if req.image_id:
        path = UPLOAD_DIR / Path(req.image_id).name
        if path.is_file():
            image_bytes = path.read_bytes()
            media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if settings.public_base_url:
            fallback_url = f"{settings.public_base_url}/api/image/{req.image_id}"

    return await ebay.publish(
        req.listing,
        req.pricing,
        fallback_image_url=fallback_url,
        image_bytes=image_bytes,
        image_media_type=media_type,
    )
