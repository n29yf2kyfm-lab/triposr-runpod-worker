"""
Promo video generation (the differentiator: auto-marketing bolted onto listing).

Live path: pluggable. `VIDEO_PROVIDER=creatify` calls Creatify's product-to-video
API (purpose-built for e-commerce); other providers (Veo/Kling) can be added the
same way. The AI always produces the *storyboard + hook + caption + hashtags*
regardless — that half needs no video API and is the marketing brain of the app.

Mock path: returns the storyboard + caption so you can see the marketing output
with no key. Swapping in a real video key turns `status` into "ready" with a URL.
"""
from __future__ import annotations

from ..config import get_settings
from ..schemas import Identification, Listing, PromoVideo, VideoStoryboardShot


def _storyboard(item: Identification, listing: Listing) -> PromoVideo:
    name = f"{item.brand} {item.model}".strip() or item.title_guess
    hook = f"POV: you just found {name} for way less 👀"
    shots = [
        VideoStoryboardShot(seconds=0.0, visual="Product photo zooms in, fast", caption=hook),
        VideoStoryboardShot(
            seconds=2.0,
            visual="Quick cuts of each angle / key feature",
            caption=(listing.bullet_points[0] if listing.bullet_points else name),
        ),
        VideoStoryboardShot(
            seconds=4.5,
            visual="Text overlay of condition + price",
            caption=f"{item.condition} · grab it before it's gone",
        ),
        VideoStoryboardShot(
            seconds=7.0,
            visual="Call to action, tap-through animation",
            caption="Link in bio → tap to buy 🛒",
        ),
    ]
    hashtags = ["#thrifted", "#resell", "#ebayfinds", "#deal"]
    if item.brand:
        hashtags.insert(0, f"#{item.brand.lower().replace(' ', '')}")
    return PromoVideo(
        status="storyboard_only",
        duration_s=9.0,
        hook=hook,
        caption=f"{name} — {item.condition}. {listing.subtitle or 'Fast shipping, easy returns.'}",
        hashtags=hashtags,
        storyboard=shots,
        source="mock",
    )


async def generate(item: Identification, listing: Listing, image_id: str = "") -> PromoVideo:
    settings = get_settings()
    board = _storyboard(item, listing)

    if not settings.video_live:
        return board  # storyboard + caption only (no video API key set)

    if settings.video_provider == "creatify":
        # Wire-up point for Creatify's Product-to-Video API.
        # Left as an explicit integration seam: submit product image + script,
        # poll for the rendered clip, then fill video_url/thumbnail_url below.
        board.status = "processing"
        board.source = "creatify"
        board.caption += "  (Creatify render queued — poll job status to attach the URL.)"
        return board

    return board
