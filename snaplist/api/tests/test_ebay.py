"""
Tests for the eBay publish path.

The publish is a multi-call sequence with several requirements eBay only
enforces at the final step, so these tests stand up a fake eBay with
httpx.MockTransport and assert on the *actual requests sent* — that the
prerequisites are met and the bodies carry the fields eBay demands. That is
verifiable without credentials; a live Sandbox run is not.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import config
from app.providers import ebay
from app.schemas import ItemSpecific, Listing, Pricing


# --- fixtures --------------------------------------------------------------


def _listing(condition: str = "Used - Good") -> Listing:
    return Listing(
        title="Sony WH-1000XM4 Wireless Headphones",
        description_html="<p>Great headphones.</p>",
        bullet_points=["ANC"],
        item_specifics=[
            ItemSpecific(name="Brand", value="Sony"),
            ItemSpecific(name="Condition", value=condition),
        ],
        keywords=["sony"],
        category_id="",
    )


def _pricing() -> Pricing:
    return Pricing(suggested_price=104.88, currency="USD", low=99, high=130)


@pytest.fixture
def live_settings(monkeypatch: pytest.MonkeyPatch) -> config.Settings:
    """A settings object that looks fully configured, pointed at Sandbox."""
    monkeypatch.setenv("EBAY_CLIENT_ID", "cid")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EBAY_USER_TOKEN", "utoken")
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv("EBAY_FALLBACK_CATEGORY_ID", "112529")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    yield settings
    config.get_settings.cache_clear()


class FakeEbay:
    """Records requests and answers with realistic eBay responses."""

    def __init__(self, *, has_location=True, policies=True, media_ok=True):
        self.requests: list[httpx.Request] = []
        self.has_location = has_location
        self.policies = policies
        self.media_ok = media_ok

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "apptok", "expires_in": 7200})

        if "/sell/inventory/v1/location/" in path:
            if request.method == "GET":
                return httpx.Response(200 if self.has_location else 404, json={})
            return httpx.Response(204)

        if "/sell/account/v1/" in path:
            if not self.policies:
                return httpx.Response(200, json={})
            kind = path.rsplit("/", 1)[-1]
            key, id_key = {
                "fulfillment_policy": ("fulfillmentPolicies", "fulfillmentPolicyId"),
                "payment_policy": ("paymentPolicies", "paymentPolicyId"),
                "return_policy": ("returnPolicies", "returnPolicyId"),
            }[kind]
            return httpx.Response(200, json={key: [{id_key: f"{kind}-1"}]})

        if "create_image_from_file" in path:
            if not self.media_ok:
                return httpx.Response(500, text="media unavailable")
            return httpx.Response(
                201,
                headers={"Location": "https://apim.sandbox.ebay.com/commerce/media/v1_beta/image/img-1"},
            )

        if "/commerce/media/v1_beta/image/img-1" in path:
            return httpx.Response(200, json={"imageUrl": "https://i.ebayimg.com/img-1.jpg"})

        if "/sell/inventory/v1/inventory_item/" in path:
            return httpx.Response(204)

        if path.endswith("/sell/inventory/v1/offer"):
            return httpx.Response(201, json={"offerId": "offer-1"})

        if path.endswith("/publish"):
            return httpx.Response(200, json={"listingId": "110000001"})

        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    def body(self, needle: str) -> dict:
        for r in self.requests:
            if needle in r.url.path and r.content:
                return json.loads(r.content)
        raise AssertionError(f"no request body matching {needle}")

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch):
    """Route every AsyncClient in the module through a FakeEbay."""

    def _install(fake: FakeEbay):
        real_init = httpx.AsyncClient.__init__

        def init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(fake.handler)
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
        return fake

    return _install


# --- condition mapping ----------------------------------------------------


@pytest.mark.parametrize(
    "human,expected",
    [
        ("New", "NEW"),
        ("Open box", "NEW_OTHER"),
        # eBay has no USED_LIKE_NEW / USED_FAIR — these must land on real values.
        ("Used - Like New", "USED_EXCELLENT"),
        ("Used - Fair", "USED_ACCEPTABLE"),
        ("Used - Good", "USED_GOOD"),
        ("For parts", "FOR_PARTS_OR_NOT_WORKING"),
        ("Used – Good", "USED_GOOD"),  # en dash
        ("total gibberish", "USED_GOOD"),  # safe default
        ("", "USED_GOOD"),
    ],
)
def test_map_condition(human: str, expected: str) -> None:
    assert ebay.map_condition(human) == expected


def test_every_mapped_condition_is_a_real_ebay_enum() -> None:
    """Guard against reintroducing an enum value eBay does not accept."""
    valid = {
        "NEW", "LIKE_NEW", "NEW_OTHER", "NEW_WITH_DEFECTS",
        "CERTIFIED_REFURBISHED", "EXCELLENT_REFURBISHED", "VERY_GOOD_REFURBISHED",
        "GOOD_REFURBISHED", "SELLER_REFURBISHED", "USED_EXCELLENT",
        "USED_VERY_GOOD", "USED_GOOD", "USED_ACCEPTABLE",
        "FOR_PARTS_OR_NOT_WORKING", "PRE_OWNED_EXCELLENT", "PRE_OWNED_FAIR",
    }
    assert set(ebay.CONDITION_MAP.values()) <= valid


# --- demo mode ------------------------------------------------------------


def test_demo_mode_returns_draft_without_calling_ebay(monkeypatch) -> None:
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_USER_TOKEN", raising=False)
    config.get_settings.cache_clear()
    import asyncio

    result = asyncio.run(ebay.publish(_listing(), _pricing()))
    config.get_settings.cache_clear()
    assert result.status == "draft"
    assert result.live is False


# --- the happy path -------------------------------------------------------


@pytest.mark.anyio
async def test_publish_sends_everything_ebay_requires(
    live_settings, patched_client
) -> None:
    fake = patched_client(FakeEbay())

    result = await ebay.publish(
        _listing(), _pricing(), image_bytes=b"jpegbytes", image_media_type="image/jpeg"
    )

    assert result.status == "published", result.message
    assert result.listing_id == "110000001"
    assert "sandbox.ebay.com/itm/110000001" in result.view_url

    # The offer must carry every publish-time requirement.
    offer = fake.body("/sell/inventory/v1/offer")
    assert offer["listingDuration"] == "GTC", "FIXED_PRICE requires GTC"
    assert offer["merchantLocationKey"]
    assert offer["categoryId"] == "112529"
    assert offer["pricingSummary"]["price"] == {"value": "104.88", "currency": "USD"}
    for key in ("fulfillmentPolicyId", "paymentPolicyId", "returnPolicyId"):
        assert offer["listingPolicies"][key], f"{key} missing — publish would fail"

    # The inventory item must have an image and a real condition enum.
    inv = fake.body("/sell/inventory/v1/inventory_item/")
    assert inv["product"]["imageUrls"] == ["https://i.ebayimg.com/img-1.jpg"]
    assert inv["condition"] == "USED_GOOD"
    # Aspects must be name -> LIST of values, not bare strings.
    assert inv["product"]["aspects"]["Brand"] == ["Sony"]


@pytest.mark.anyio
async def test_condition_from_listing_reaches_ebay(live_settings, patched_client) -> None:
    """A seller editing the condition in the UI must change what eBay receives."""
    fake = patched_client(FakeEbay())
    await ebay.publish(
        _listing(condition="Used - Like New"), _pricing(), image_bytes=b"x"
    )
    assert fake.body("/sell/inventory/v1/inventory_item/")["condition"] == "USED_EXCELLENT"


@pytest.mark.anyio
async def test_creates_location_when_missing(live_settings, patched_client) -> None:
    fake = patched_client(FakeEbay(has_location=False))
    result = await ebay.publish(_listing(), _pricing(), image_bytes=b"x")
    assert result.status == "published", result.message
    posts = [
        r for r in fake.requests
        if "/location/" in r.url.path and r.method == "POST"
    ]
    assert len(posts) == 1, "should create the location exactly once"
    assert json.loads(posts[0].content)["location"]["address"]["country"] == "US"


# --- failure modes --------------------------------------------------------


@pytest.mark.anyio
async def test_missing_business_policies_fails_with_actionable_message(
    live_settings, patched_client
) -> None:
    patched_client(FakeEbay(policies=False))
    result = await ebay.publish(_listing(), _pricing(), image_bytes=b"x")
    assert result.status == "error"
    assert "business policies" in result.message.lower()
    assert "Seller Hub" in result.message


@pytest.mark.anyio
async def test_media_failure_falls_back_to_self_hosted_url(
    live_settings, patched_client
) -> None:
    """Media API is on a beta path; a failure there must not sink the publish."""
    fake = patched_client(FakeEbay(media_ok=False))
    result = await ebay.publish(
        _listing(),
        _pricing(),
        fallback_image_url="https://example.com/photo.jpg",
        image_bytes=b"x",
    )
    assert result.status == "published", result.message
    inv = fake.body("/sell/inventory/v1/inventory_item/")
    assert inv["product"]["imageUrls"] == ["https://example.com/photo.jpg"]


@pytest.mark.anyio
async def test_no_image_at_all_is_refused_before_calling_ebay(
    live_settings, patched_client
) -> None:
    """eBay requires an image; better a clear refusal than a doomed publish."""
    fake = patched_client(FakeEbay(media_ok=False))
    result = await ebay.publish(_listing(), _pricing(), image_bytes=b"x")
    assert result.status == "error"
    assert "no image" in result.message.lower()
    assert not any("inventory_item" in p for p in fake.paths())


@pytest.mark.anyio
async def test_no_category_in_sandbox_without_fallback_is_refused(
    live_settings, patched_client, monkeypatch
) -> None:
    monkeypatch.setenv("EBAY_FALLBACK_CATEGORY_ID", "")
    config.get_settings.cache_clear()
    fake = patched_client(FakeEbay())
    result = await ebay.publish(_listing(), _pricing(), image_bytes=b"x")
    assert result.status == "error"
    assert "category" in result.message.lower()
    assert not any("inventory_item" in p for p in fake.paths())


@pytest.mark.anyio
async def test_sandbox_skips_taxonomy_because_it_returns_boilerplate(
    live_settings, patched_client
) -> None:
    fake = patched_client(FakeEbay())
    await ebay.publish(_listing(), _pricing(), image_bytes=b"x")
    assert not any("taxonomy" in p for p in fake.paths())
