"""
Publish to eBay via the official Sell Inventory API.

eBay separates *what the thing is* from *how you're selling it* from *go live*,
so a publish is a sequence, not one call. Several prerequisites are only
enforced at publish time, which is why they are all handled up front here:

    ensure location    POST  /sell/inventory/v1/location/{key}      (once)
    resolve category   GET   /commerce/taxonomy/v1/...              (app token)
    upload image       POST  /commerce/media/v1_beta/image/...      (Media API)
    fetch policies     GET   /sell/account/v1/{payment,return,fulfillment}_policy
    inventory item     PUT   /sell/inventory/v1/inventory_item/{sku}
    offer              POST  /sell/inventory/v1/offer               -> offerId
    publish            POST  /sell/inventory/v1/offer/{id}/publish   -> listingId

Hard requirements confirmed against eBay's docs — all of these fail the publish
if missing, and none of them fall back to account defaults:
  * `listingPolicies` with all three business policy IDs
  * `merchantLocationKey` (an inventory location must exist)
  * `listingDuration: GTC` for FIXED_PRICE
  * at least one image on the inventory item
  * a valid leaf `categoryId`

Runs against the Sandbox by default (nothing goes live, no fees).
"""
from __future__ import annotations

import base64
import re
import time

import httpx

from ..config import Settings, get_settings
from ..schemas import Listing, Pricing, PublishResult

# --- condition -------------------------------------------------------------
# Our vision step produces human strings; eBay wants an enum. Note that
# USED_LIKE_NEW and USED_FAIR do NOT exist in eBay's ConditionEnum, so the
# closest real values are used instead.
CONDITION_MAP: dict[str, str] = {
    "new": "NEW",
    "open box": "NEW_OTHER",
    "new other": "NEW_OTHER",
    "used - like new": "USED_EXCELLENT",
    "like new": "USED_EXCELLENT",
    "used - excellent": "USED_EXCELLENT",
    "used - very good": "USED_VERY_GOOD",
    "used - good": "USED_GOOD",
    "used": "USED_GOOD",
    "used - fair": "USED_ACCEPTABLE",
    "used - acceptable": "USED_ACCEPTABLE",
    "for parts": "FOR_PARTS_OR_NOT_WORKING",
    "for parts or not working": "FOR_PARTS_OR_NOT_WORKING",
}


def map_condition(human: str) -> str:
    """Human condition string -> eBay ConditionEnum, defaulting to USED_GOOD."""
    key = " ".join((human or "").lower().split())
    if key in CONDITION_MAP:
        return CONDITION_MAP[key]
    # Tolerate variants like "Used – Good" (en dash) or "used/good".
    norm = re.sub(r"[^a-z ]+", " ", key)
    norm = " ".join(norm.split())
    if norm in CONDITION_MAP:
        return CONDITION_MAP[norm]
    for phrase, enum in CONDITION_MAP.items():
        if phrase in norm:
            return enum
    return "USED_GOOD"


def _sku(listing: Listing) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", listing.title.lower()).strip("-")[:40]
    return f"SNAP-{slug}-{int(time.time())}"


class PublishError(Exception):
    """A step failed; carries a message meant for the seller to read."""


def _fail(step: str, res: httpx.Response) -> PublishError:
    return PublishError(f"{step} failed ({res.status_code}): {res.text[:400]}")


# --- app token (taxonomy only) --------------------------------------------
# Taxonomy needs only the basic scope, so a client-credentials token works —
# no seller consent required. Cached until shortly before it expires.
_app_token_cache: dict[str, tuple[str, float]] = {}


async def _app_token(client: httpx.AsyncClient, s: Settings) -> str:
    cached = _app_token_cache.get(s.ebay_env)
    if cached and cached[1] > time.time():
        return cached[0]

    basic = base64.b64encode(
        f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()
    ).decode()
    res = await client.post(
        f"{s.ebay_base}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
    )
    if res.status_code >= 400:
        raise _fail("App token", res)
    body = res.json()
    token = body.get("access_token", "")
    _app_token_cache[s.ebay_env] = (token, time.time() + int(body.get("expires_in", 7200)) - 60)
    return token


# --- category -------------------------------------------------------------
async def resolve_category(client: httpx.AsyncClient, s: Settings, title: str) -> str:
    """
    Resolve a leaf category from the listing title.

    eBay does not support get_category_suggestions in Sandbox (it returns
    boilerplate regardless of the query), so Sandbox goes straight to the
    configured fallback rather than publishing a nonsense category.
    """
    if s.ebay_env != "production":
        return s.ebay_fallback_category_id

    try:
        token = await _app_token(client, s)
        head = {"Authorization": f"Bearer {token}"}
        tree = await client.get(
            f"{s.ebay_base}/commerce/taxonomy/v1/get_default_category_tree_id",
            params={"marketplace_id": s.ebay_marketplace_id},
            headers=head,
        )
        if tree.status_code >= 400:
            return s.ebay_fallback_category_id
        tree_id = tree.json().get("categoryTreeId", "")

        sug = await client.get(
            f"{s.ebay_base}/commerce/taxonomy/v1/category_tree/{tree_id}"
            "/get_category_suggestions",
            params={"q": title},
            headers=head,
        )
        # A 204 (no content) is a documented possibility, not an error.
        if sug.status_code == 204 or sug.status_code >= 400:
            return s.ebay_fallback_category_id
        suggestions = sug.json().get("categorySuggestions") or []
        if not suggestions:
            return s.ebay_fallback_category_id
        return str(suggestions[0].get("category", {}).get("categoryId", "")) or (
            s.ebay_fallback_category_id
        )
    except (httpx.HTTPError, PublishError, ValueError):
        return s.ebay_fallback_category_id


# --- inventory location ---------------------------------------------------
async def ensure_location(client: httpx.AsyncClient, s: Settings) -> str:
    """Every offer must reference a location, so create it if absent."""
    key = s.ebay_location_key
    existing = await client.get(f"{s.ebay_base}/sell/inventory/v1/location/{key}")
    if existing.status_code < 400:
        return key

    body = {
        "location": {
            "address": {
                "postalCode": s.ebay_location_postal_code,
                "country": s.ebay_location_country,
            }
        },
        "name": "SnapList default location",
        "merchantLocationStatus": "ENABLED",
        "locationTypes": ["WAREHOUSE"],
    }
    created = await client.post(
        f"{s.ebay_base}/sell/inventory/v1/location/{key}", json=body
    )
    # 409 means another request already created it — that is success for us.
    if created.status_code >= 400 and created.status_code != 409:
        raise _fail("Create inventory location", created)
    return key


# --- business policies ----------------------------------------------------
_POLICY_KINDS = (
    ("fulfillment_policy", "fulfillmentPolicies", "fulfillmentPolicyId"),
    ("payment_policy", "paymentPolicies", "paymentPolicyId"),
    ("return_policy", "returnPolicies", "returnPolicyId"),
)


async def fetch_policy_ids(client: httpx.AsyncClient, s: Settings) -> dict[str, str]:
    """
    Collect the three business policy IDs a publish requires.

    Configured IDs win; otherwise the seller's first policy of each kind is
    used. Missing any of the three is a hard failure with an actionable
    message, because eBay will not substitute a default.
    """
    configured = {
        "fulfillmentPolicyId": s.ebay_fulfillment_policy_id,
        "paymentPolicyId": s.ebay_payment_policy_id,
        "returnPolicyId": s.ebay_return_policy_id,
    }
    out = {k: v for k, v in configured.items() if v}
    missing_kinds = [k for k in _POLICY_KINDS if not out.get(k[2])]

    for path, list_key, id_key in missing_kinds:
        res = await client.get(
            f"{s.ebay_base}/sell/account/v1/{path}",
            params={"marketplace_id": s.ebay_marketplace_id},
        )
        if res.status_code >= 400:
            continue
        policies = res.json().get(list_key) or []
        if policies:
            out[id_key] = str(policies[0].get(id_key, ""))

    absent = [k for _, _, k in _POLICY_KINDS if not out.get(k)]
    if absent:
        raise PublishError(
            "Cannot publish: missing business policies "
            f"({', '.join(absent)}). eBay requires payment, return and shipping "
            "policies before an offer can go live — opt into Business Policies "
            "and create one of each in eBay Seller Hub, or set the "
            "EBAY_*_POLICY_ID variables."
        )
    return out


# --- images ---------------------------------------------------------------
async def upload_image(
    client: httpx.AsyncClient, s: Settings, image_bytes: bytes, media_type: str
) -> str:
    """
    Upload the photo to eBay Picture Services via the Media API and return the
    hosted URL. This is preferred over self-hosting because eBay has to fetch
    self-hosted images over the internet — it cannot reach localhost.

    createImageFromFile returns 201 with an EMPTY body; the image id arrives in
    the Location header, which then has to be fetched to get the real URL.
    """
    res = await client.post(
        f"{s.ebay_media_base}/commerce/media/v1_beta/image/create_image_from_file",
        files={"image": ("photo", image_bytes, media_type or "image/jpeg")},
    )
    if res.status_code >= 400:
        raise _fail("Image upload", res)

    location = res.headers.get("location") or res.headers.get("Location") or ""
    if not location:
        raise PublishError("Image upload succeeded but returned no Location header.")

    detail = await client.get(location)
    if detail.status_code >= 400:
        raise _fail("Image lookup", detail)
    url = detail.json().get("imageUrl", "")
    if not url:
        raise PublishError("Image lookup returned no imageUrl.")
    return url


async def _image_url(
    client: httpx.AsyncClient,
    s: Settings,
    image_bytes: bytes | None,
    media_type: str,
    fallback_url: str,
) -> str:
    """Prefer an eBay-hosted image; fall back to a self-hosted public URL."""
    if image_bytes:
        try:
            return await upload_image(client, s, image_bytes, media_type)
        except (PublishError, httpx.HTTPError, ValueError):
            # Media API is on a beta path with undocumented Sandbox support, so
            # a failure here should not sink an otherwise valid publish.
            pass
    return fallback_url


# --- mock -----------------------------------------------------------------
def _mock(listing: Listing) -> PublishResult:
    return PublishResult(
        status="draft",
        listing_id=_sku(listing),
        view_url="",
        environment="sandbox",
        live=False,
        message="DEMO MODE — set EBAY_CLIENT_ID + EBAY_USER_TOKEN to publish to the "
        "eBay Sandbox. This draft was assembled but not sent to eBay.",
    )


# --- publish --------------------------------------------------------------
async def publish(
    listing: Listing,
    pricing: Pricing,
    fallback_image_url: str = "",
    image_bytes: bytes | None = None,
    image_media_type: str = "image/jpeg",
) -> PublishResult:
    s = get_settings()
    if not s.ebay_live:
        return _mock(listing)

    sku = _sku(listing)
    headers = {
        "Authorization": f"Bearer {s.ebay_user_token}",
        "Content-Type": "application/json",
        # createOrReplaceInventoryItem requires this; omitting it yields opaque 400s.
        "Content-Language": "en-US",
    }

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        try:
            location_key = await ensure_location(client, s)
            policies = await fetch_policy_ids(client, s)
            category_id = await resolve_category(client, s, listing.title)
            if not category_id:
                raise PublishError(
                    "Cannot publish: no category resolved. eBay requires a leaf "
                    "category ID. Sandbox does not support category suggestions, "
                    "so set EBAY_FALLBACK_CATEGORY_ID to test there."
                )

            image_url = await _image_url(
                client, s, image_bytes, image_media_type, fallback_image_url
            )
            if not image_url:
                raise PublishError(
                    "Cannot publish: no image. eBay requires at least one image "
                    "per listing. The Media API upload was unavailable and no "
                    "public image URL was configured (set PUBLIC_BASE_URL)."
                )

            inv_body = {
                "product": {
                    "title": listing.title,
                    "description": listing.description_html,
                    "aspects": {
                        sp.name: [sp.value] for sp in listing.item_specifics if sp.value
                    },
                    "imageUrls": [image_url],
                },
                "condition": map_condition(pricing_condition(listing)),
                "availability": {"shipToLocationAvailability": {"quantity": 1}},
            }
            inv = await client.put(
                f"{s.ebay_base}/sell/inventory/v1/inventory_item/{sku}", json=inv_body
            )
            if inv.status_code >= 400:
                raise _fail("Inventory item", inv)

            offer_body = {
                "sku": sku,
                "marketplaceId": s.ebay_marketplace_id,
                "format": "FIXED_PRICE",
                # FIXED_PRICE offers must be GTC — eBay rejects other durations.
                "listingDuration": "GTC",
                "availableQuantity": 1,
                "categoryId": category_id,
                "listingDescription": listing.description_html,
                "merchantLocationKey": location_key,
                "listingPolicies": policies,
                "pricingSummary": {
                    "price": {
                        "value": str(pricing.suggested_price),
                        "currency": pricing.currency,
                    }
                },
            }
            offer = await client.post(
                f"{s.ebay_base}/sell/inventory/v1/offer", json=offer_body
            )
            if offer.status_code >= 400:
                raise _fail("Offer create", offer)
            offer_id = offer.json().get("offerId", "")

            pub = await client.post(
                f"{s.ebay_base}/sell/inventory/v1/offer/{offer_id}/publish"
            )
            if pub.status_code >= 400:
                raise PublishError(
                    f"Publish failed ({pub.status_code}): {pub.text[:400]}. "
                    "A common cause is missing required item specifics for the "
                    "resolved category."
                )
            listing_id = pub.json().get("listingId", "")

        except PublishError as e:
            return PublishResult(
                status="error", environment=s.ebay_env, message=str(e)
            )
        except httpx.HTTPError as e:
            return PublishResult(
                status="error",
                environment=s.ebay_env,
                message=f"Network error talking to eBay: {e}",
            )

    host = "www.ebay.com" if s.ebay_env == "production" else "www.sandbox.ebay.com"
    return PublishResult(
        status="published",
        listing_id=listing_id,
        view_url=f"https://{host}/itm/{listing_id}",
        environment=s.ebay_env,
        live=True,
        message="Published to eBay.",
    )


def pricing_condition(listing: Listing) -> str:
    """
    Pull the condition out of the listing's item specifics.

    The condition lives there because the seller can edit it in the UI, so the
    listing is the source of truth by the time we publish.
    """
    for sp in listing.item_specifics:
        if sp.name.strip().lower() == "condition" and sp.value:
            return sp.value
    return "Used - Good"
