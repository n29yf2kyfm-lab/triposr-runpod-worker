"""
Publish to eBay via the official Sell Inventory API.

Flow (Inventory API): create/replace an inventory item -> create an offer ->
publish the offer. Runs against the **Sandbox** by default (safe: nothing goes
live, no fees). Flip EBAY_ENV=production + real creds to list for real.

Requires a user OAuth token (EBAY_USER_TOKEN) that authorises listing on the
seller's own account. Without creds this returns a realistic draft so the UI
completes the flow.

Note: a real publish also needs the seller's business policies (payment/return/
shipping) configured on their eBay account — if publish fails for that reason we
surface eBay's message rather than hiding it.
"""
from __future__ import annotations

import re
import time

import httpx

from ..config import get_settings
from ..schemas import Listing, Pricing, PublishResult


def _sku(listing: Listing) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", listing.title.lower()).strip("-")[:40]
    return f"SNAP-{slug}-{int(time.time())}"


def _mock(listing: Listing, pricing: Pricing) -> PublishResult:
    return PublishResult(
        status="draft",
        listing_id=_sku(listing),
        view_url="",
        environment="sandbox",
        live=False,
        message="DEMO MODE — set EBAY_CLIENT_ID + EBAY_USER_TOKEN to publish to the "
        "eBay Sandbox. This draft was assembled but not sent to eBay.",
    )


async def publish(listing: Listing, pricing: Pricing, image_url: str = "") -> PublishResult:
    settings = get_settings()
    if not settings.ebay_live:
        return _mock(listing, pricing)

    sku = _sku(listing)
    base = settings.ebay_base
    headers = {
        "Authorization": f"Bearer {settings.ebay_user_token}",
        "Content-Type": "application/json",
        "Content-Language": "en-US",
    }
    specifics = {s.name: [s.value] for s in listing.item_specifics if s.value}

    inv_body = {
        "product": {
            "title": listing.title,
            "description": listing.description_html,
            "aspects": specifics,
            "imageUrls": [image_url] if image_url else [],
        },
        "condition": "USED_GOOD",
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
    }

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        inv = await client.put(
            f"{base}/sell/inventory/v1/inventory_item/{sku}", json=inv_body
        )
        if inv.status_code >= 400:
            return PublishResult(
                status="error",
                environment=settings.ebay_env,
                message=f"Inventory item failed ({inv.status_code}): {inv.text[:400]}",
            )

        offer_body = {
            "sku": sku,
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": listing.category_id or "",
            "listingDescription": listing.description_html,
            "pricingSummary": {
                "price": {"value": str(pricing.suggested_price), "currency": pricing.currency}
            },
        }
        offer = await client.post(
            f"{base}/sell/inventory/v1/offer", json=offer_body
        )
        if offer.status_code >= 400:
            return PublishResult(
                status="error",
                environment=settings.ebay_env,
                message=f"Offer create failed ({offer.status_code}): {offer.text[:400]}",
            )
        offer_id = offer.json().get("offerId", "")

        pub = await client.post(
            f"{base}/sell/inventory/v1/offer/{offer_id}/publish"
        )
        if pub.status_code >= 400:
            return PublishResult(
                status="error",
                listing_id=offer_id,
                environment=settings.ebay_env,
                message=f"Publish failed ({pub.status_code}): {pub.text[:400]}. "
                "Most common cause: business policies not set on the seller account.",
            )
        listing_id = pub.json().get("listingId", "")

    view = (
        f"https://www.sandbox.ebay.com/itm/{listing_id}"
        if settings.ebay_env == "sandbox"
        else f"https://www.ebay.com/itm/{listing_id}"
    )
    return PublishResult(
        status="published",
        listing_id=listing_id,
        view_url=view,
        environment=settings.ebay_env,
        live=True,
        message="Published to eBay.",
    )
