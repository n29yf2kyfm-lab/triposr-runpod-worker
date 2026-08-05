"""
Generate the marketplace listing (SEO title, description, item specifics).

Live path: Anthropic Claude. The prompt encodes what actually moves the needle
on eBay's Cassini ranking: a keyword-front-loaded title within 80 chars and
COMPLETE item specifics (completeness lifts rank more than clever prose).

Mock path: assembles a solid listing from the identification + pricing.
"""
from __future__ import annotations

import json

import httpx

from ..config import get_settings
from ..schemas import Identification, ItemSpecific, Listing, Pricing

_PROMPT = """You write high-converting eBay listings. Given the item JSON, return STRICT JSON:
{
 "title": "<= 80 chars, keyword-front-loaded: Brand Model Type Key-Feature Condition",
 "subtitle": "short optional",
 "description_html": "clean HTML: 2-3 short paragraphs + a <ul> of features + a condition note",
 "bullet_points": ["5-7 scannable selling points"],
 "item_specifics": [{"name":"Brand","value":"..."}, ...  fill EVERY field you can, this drives ranking],
 "keywords": ["8-12 backend search keywords buyers type"],
 "category_id": "best-guess eBay leaf category id as a string, or ''"
}
Be accurate to the item; do not invent specs that aren't implied. Return ONLY the JSON."""


def _title(item: Identification) -> str:
    base = item.title_guess.strip() or " ".join(p for p in [item.brand, item.model] if p)
    if item.brand and item.brand.lower() not in base.lower():
        base = f"{item.brand} {base}"
    # de-duplicate repeated words while preserving order (e.g. model twice)
    seen: set[str] = set()
    words: list[str] = []
    for w in base.split():
        key = w.lower()
        if key not in seen:
            seen.add(key)
            words.append(w)
    base = " ".join(words)
    tail = f" — {item.condition}"
    return (base[: 80 - len(tail)].strip() + tail)[:80]


def _mock(item: Identification, pricing: Pricing) -> Listing:
    specifics = [
        ItemSpecific(name="Brand", value=item.brand or "Unbranded"),
        ItemSpecific(name="Model", value=item.model or "N/A"),
        ItemSpecific(name="Condition", value=item.condition),
        ItemSpecific(name="Color", value=item.color or "N/A"),
        ItemSpecific(name="Material", value=item.material or "N/A"),
    ] + item.attributes
    bullets = [
        f"{item.brand} {item.model}".strip() or item.title_guess,
        f"Condition: {item.condition}",
        f"Color: {item.color}" if item.color else "Fully tested and working",
        "Ships fast with tracking",
        "30-day returns accepted",
    ]
    desc = (
        f"<p>{item.title_guess} in <strong>{item.condition}</strong> condition.</p>"
        f"<p>{item.notes or 'Inspected and ready to ship.'}</p>"
        "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
        "<p><em>Any questions, just ask before buying.</em></p>"
    )
    return Listing(
        title=_title(item),
        subtitle="Fast free shipping · 30-day returns",
        description_html=desc,
        bullet_points=bullets,
        item_specifics=specifics,
        keywords=[
            w
            for w in [item.brand, item.model, item.color, item.category.split(">")[-1].strip()]
            if w
        ]
        or ["electronics", "gadget"],
        category_id="",
        source="mock",
    )


async def generate(item: Identification, pricing: Pricing) -> Listing:
    settings = get_settings()
    if not settings.ai_live:
        return _mock(item, pricing)

    prompt_item = {**item.model_dump(), "suggested_price": pricing.suggested_price}
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 1500,
        "messages": [
            {
                "role": "user",
                "content": f"{_PROMPT}\n\nItem JSON:\n{json.dumps(prompt_item)}",
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
            b["text"] for b in r.json()["content"] if b["type"] == "text"
        )

    data = _extract_json(text)
    if not data.get("title"):
        return _mock(item, pricing)
    return Listing(
        title=data.get("title", _title(item))[:80],
        subtitle=data.get("subtitle", ""),
        description_html=data.get("description_html", ""),
        bullet_points=data.get("bullet_points", []),
        item_specifics=[
            ItemSpecific(**s) for s in data.get("item_specifics", []) if s.get("name")
        ],
        keywords=data.get("keywords", []),
        category_id=str(data.get("category_id", "")),
        source="anthropic",
    )


def _extract_json(text: str) -> dict:
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
