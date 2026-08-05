"""
Photo -> product identification.

Live path: Anthropic Claude vision (multimodal). Strong at category, colour,
material and condition. It is deliberately instructed NOT to invent an exact
model number when unsure — that is the #1 failure mode of photo identification,
so low confidence is returned instead of a hallucinated SKU.

Mock path: returns a realistic sample so the UI works with no API key.
"""
from __future__ import annotations

import base64
import json

import httpx

from ..config import get_settings
from ..schemas import Identification, ItemSpecific

_PROMPT = """You are a product cataloguing assistant for online resellers.
Look at this photo of a single item for sale and return STRICT JSON with keys:
title_guess (short name a buyer would search), brand, model, category, condition
(one of: New, Open box, Used - Like New, Used - Good, Used - Fair, For parts),
color, material, attributes (array of {name,value} — e.g. Size, Capacity, Style),
confidence (0..1 for how sure you are overall), notes (anything a seller should verify).

Rules:
- If you cannot clearly read a brand or model, leave it "" and lower the confidence.
  NEVER guess a specific model number you cannot see. A blank is better than a wrong SKU.
- Base condition only on what is visible.
Return ONLY the JSON object, no prose."""


def _mock(filename: str = "") -> Identification:
    return Identification(
        title_guess="Sony WH-1000XM4 Wireless Noise-Cancelling Headphones",
        brand="Sony",
        model="WH-1000XM4",
        category="Consumer Electronics > Headphones",
        condition="Used - Good",
        color="Black",
        material="Plastic / Protein leather",
        attributes=[
            ItemSpecific(name="Connectivity", value="Bluetooth / Wireless"),
            ItemSpecific(name="Type", value="Over-Ear"),
            ItemSpecific(name="Features", value="Active Noise Cancellation"),
        ],
        confidence=0.82,
        notes="DEMO DATA — set ANTHROPIC_API_KEY to identify your real photo. "
        "Verify the model on the headband before listing.",
        source="mock",
    )


async def identify(image_bytes: bytes, media_type: str, filename: str = "") -> Identification:
    settings = get_settings()
    if not settings.ai_live:
        return _mock(filename)

    b64 = base64.standard_b64encode(image_bytes).decode()
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type or "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages", json=payload, headers=headers
        )
        r.raise_for_status()
        text = "".join(
            block["text"] for block in r.json()["content"] if block["type"] == "text"
        )

    data = _extract_json(text)
    attrs = [ItemSpecific(**a) for a in data.get("attributes", []) if a.get("name")]
    return Identification(
        title_guess=data.get("title_guess", "Unknown item"),
        brand=data.get("brand", ""),
        model=data.get("model", ""),
        category=data.get("category", ""),
        condition=data.get("condition", "Used - Good"),
        color=data.get("color", ""),
        material=data.get("material", ""),
        attributes=attrs,
        confidence=float(data.get("confidence", 0.5)),
        notes=data.get("notes", ""),
        source="anthropic",
    )


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction — models sometimes wrap output in prose/fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
