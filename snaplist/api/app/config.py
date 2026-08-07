"""
Central configuration.

Every external integration is optional. If a key is missing, that provider
falls back to realistic *mock* data so the whole app runs end-to-end with zero
setup. Drop the real keys into a `.env` file (see `.env.example`) to go live.

Values are read in `__init__`, not at class level, so constructing a Settings
always reflects the current environment. Class-level `_get(...)` defaults would
be evaluated once at import time, which silently ignores any later change.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    def __init__(self) -> None:
        # --- AI: vision + copywriting (Anthropic) ---
        self.anthropic_api_key = _get("ANTHROPIC_API_KEY")
        # The app's own model choice — change freely. Not tied to any host model.
        self.anthropic_model = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

        # --- Pricing / visual match (SerpApi Google Lens) ---
        self.serpapi_key = _get("SERPAPI_KEY")

        # --- Promo video generation (pluggable) ---
        self.video_api_key = _get("VIDEO_API_KEY")
        self.video_provider = _get("VIDEO_PROVIDER", "mock")  # mock | creatify | veo

        # --- eBay (Sandbox by default) ---
        self.ebay_env = _get("EBAY_ENV", "sandbox")  # sandbox | production
        self.ebay_client_id = _get("EBAY_CLIENT_ID")
        self.ebay_client_secret = _get("EBAY_CLIENT_SECRET")
        # A user OAuth token authorises listing on *their* eBay account.
        self.ebay_user_token = _get("EBAY_USER_TOKEN")
        self.ebay_marketplace_id = _get("EBAY_MARKETPLACE_ID", "EBAY_US")

        # Seller's inventory location. Every offer must reference one, so the
        # app creates it on first publish if it does not exist yet.
        self.ebay_location_key = _get("EBAY_LOCATION_KEY", "snaplist-default")
        self.ebay_location_postal_code = _get("EBAY_LOCATION_POSTAL_CODE", "94105")
        self.ebay_location_country = _get("EBAY_LOCATION_COUNTRY", "US")

        # Business policy IDs. Left blank, the app looks up the seller's first
        # policy of each kind — publishing requires all three.
        self.ebay_fulfillment_policy_id = _get("EBAY_FULFILLMENT_POLICY_ID")
        self.ebay_payment_policy_id = _get("EBAY_PAYMENT_POLICY_ID")
        self.ebay_return_policy_id = _get("EBAY_RETURN_POLICY_ID")

        # Taxonomy's category-suggestion call is not supported in Sandbox (it
        # returns boilerplate), so Sandbox runs need a category to fall back on.
        self.ebay_fallback_category_id = _get("EBAY_FALLBACK_CATEGORY_ID")

        # Optional: public base URL this API is reachable at, e.g. an ngrok
        # tunnel. Only a fallback if the Media API upload is unavailable — eBay
        # fetches self-hosted images over the internet and cannot see localhost.
        self.public_base_url = _get("PUBLIC_BASE_URL").rstrip("/")

        self.cors_origins = [
            o.strip()
            for o in _get("CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ]

    # --- Feature availability flags (surfaced to the UI) ---
    @property
    def ai_live(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def pricing_live(self) -> bool:
        return bool(self.serpapi_key)

    @property
    def video_live(self) -> bool:
        return self.video_provider != "mock" and bool(self.video_api_key)

    @property
    def ebay_live(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_user_token)

    @property
    def ebay_base(self) -> str:
        return (
            "https://api.ebay.com"
            if self.ebay_env == "production"
            else "https://api.sandbox.ebay.com"
        )

    @property
    def ebay_media_base(self) -> str:
        """
        The Media API lives on its own host and is still on a `v1_beta` path.
        Sandbox support is undocumented, so an upload failure here is treated as
        recoverable and falls back to a self-hosted image URL.
        """
        return (
            "https://apim.ebay.com"
            if self.ebay_env == "production"
            else "https://apim.sandbox.ebay.com"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
