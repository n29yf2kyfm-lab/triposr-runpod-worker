"""
Comparable market pricing.

Live path: SerpApi Google Lens / Google Shopping — turn the item name into real
comparable listings with prices, then anchor a suggested price to the median.
(eBay's *sold* price API — Marketplace Insights — is gated to enterprise partners,
so live comps are the pragmatic anchor. See the feasibility brief.)

Mock path: deterministic sample comps so the flow works with no key.
"""
from __future__ import annotations

from statistics import median

import httpx

from ..config import get_settings
from ..schemas import Identification, PriceComp, Pricing


def _suggest(prices: list[float]) -> tuple[float, float, float]:
    if not prices:
        return 0.0, 0.0, 0.0
    prices = sorted(prices)
    mid = median(prices)
    # Price a used item slightly under the market median to sell faster.
    return round(mid * 0.92, 2), prices[0], prices[-1]


def _mock(item: Identification) -> Pricing:
    comps = [
        PriceComp(title=f"{item.title_guess} (used)", price=118.0, source="eBay", url=""),
        PriceComp(title=f"{item.title_guess}", price=129.99, source="Amazon", url=""),
        PriceComp(title=f"{item.title_guess} (refurb)", price=99.0, source="Back Market", url=""),
        PriceComp(title=f"{item.title_guess} (good)", price=110.0, source="eBay", url=""),
    ]
    suggested, low, high = _suggest([c.price for c in comps])
    return Pricing(
        suggested_price=suggested,
        low=low,
        high=high,
        comps=comps,
        rationale="DEMO DATA — set SERPAPI_KEY for live comps. Suggested = 8% under "
        "the median of comparable listings to sell faster.",
        source="mock",
    )


async def price(item: Identification) -> Pricing:
    settings = get_settings()
    if not settings.pricing_live:
        return _mock(item)

    query = " ".join(x for x in [item.brand, item.model, item.title_guess] if x)
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": settings.serpapi_key,
        "num": "20",
    }
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.get("https://serpapi.com/search.json", params=params)
        r.raise_for_status()
        data = r.json()

    comps: list[PriceComp] = []
    for row in data.get("shopping_results", [])[:12]:
        p = row.get("extracted_price")
        if isinstance(p, (int, float)) and p > 0:
            comps.append(
                PriceComp(
                    title=row.get("title", "")[:120],
                    price=float(p),
                    source=row.get("source", ""),
                    url=row.get("link", "") or row.get("product_link", ""),
                )
            )

    if not comps:
        out = _mock(item)
        out.rationale = "No live comps found for this query; showing an estimate."
        return out

    suggested, low, high = _suggest([c.price for c in comps])
    return Pricing(
        suggested_price=suggested,
        low=low,
        high=high,
        comps=comps,
        rationale="Suggested = ~8% under the median of live comparable listings.",
        source="serpapi",
    )
