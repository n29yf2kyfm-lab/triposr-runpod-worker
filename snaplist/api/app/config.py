"""
Central configuration.

Every external integration is optional. If a key is missing, that provider
falls back to realistic *mock* data so the whole app runs end-to-end with zero
setup. Drop the real keys into a `.env` file (see `.env.example`) to go live.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    # --- AI: vision + copywriting (Anthropic) ---
    anthropic_api_key: str = _get("ANTHROPIC_API_KEY")
    # The app's own model choice — change freely. Not tied to any host model.
    anthropic_model: str = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

    # --- Pricing / visual match (SerpApi Google Lens) ---
    serpapi_key: str = _get("SERPAPI_KEY")

    # --- Promo video generation (pluggable) ---
    video_api_key: str = _get("VIDEO_API_KEY")
    video_provider: str = _get("VIDEO_PROVIDER", "mock")  # mock | creatify | veo

    # --- eBay (Sandbox by default) ---
    ebay_env: str = _get("EBAY_ENV", "sandbox")  # sandbox | production
    ebay_client_id: str = _get("EBAY_CLIENT_ID")
    ebay_client_secret: str = _get("EBAY_CLIENT_SECRET")
    # A user OAuth token authorises listing on *their* eBay account.
    ebay_user_token: str = _get("EBAY_USER_TOKEN")

    cors_origins: list[str] = [
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
