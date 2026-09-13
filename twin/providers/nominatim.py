"""Worldwide geocoding from OpenStreetMap data.

Covers the whole planet at wildly varying density, which is the honest
position: a Birmingham postcode resolves to a building, a village in
rural Chad may resolve to the village. The `accuracy_m` and
`classification` carried back say which you got, so the map can zoom
appropriately and the property panel can decline to claim a house.

THE ENDPOINT IS NOT THE DATA. The OSM data is ODbL and free to use; the
public nominatim.openstreetmap.org service is a volunteer box with a
1 req/s cap and a mandatory User-Agent. Production self-hosts. That
distinction is in licences.py and enforced by the cache's throttle, and
the base URL is an env var so swapping to a self-hosted instance is
configuration, not a code change.
"""
from __future__ import annotations

import json
import os
import urllib.parse

import requests

from .. import cache as cache_mod
from ..provenance import CLASS_VERIFIED, Missing, Provenance
from .base import (CAP_AVAILABLE, CAP_LIMITED, CAP_NONE, Capability, Provider,
                   sourced, transport_missing)

BASE = os.environ.get("TWIN_NOMINATIM", "https://nominatim.openstreetmap.org")
UA = os.environ.get(
    "TWIN_USER_AGENT",
    "triposr-twin/0.1 (property digital twin; contact via repository)")
LICENCE = "nominatim-policy"
MIN_INTERVAL = float(os.environ.get("TWIN_NOMINATIM_INTERVAL", "1.1"))

# Nominatim reports how precise a hit is only indirectly. These are the
# published place classes mapped to a positional accuracy we are willing
# to state — deliberately pessimistic, because an over-confident accuracy
# is what puts a red line through a neighbour's garden.
_ACCURACY_M = {
    "building": 5.0, "house": 5.0, "address": 8.0,
    "postcode": 120.0, "street": 40.0, "highway": 40.0,
    "suburb": 800.0, "city": 3000.0, "town": 1500.0, "village": 800.0,
    "county": 20000.0, "state": 60000.0, "country": 200000.0,
}


def _accuracy(item) -> float:
    for k in (item.get("addresstype"), item.get("type"), item.get("class")):
        if k in _ACCURACY_M:
            return _ACCURACY_M[k]
    # Fall back on the bounding box: a hit whose box is 2 km across is
    # not a house, whatever it calls itself.
    try:
        s, n, w, e = (float(v) for v in item["boundingbox"])
        span = max((n - s) * 111320.0, (e - w) * 78000.0)
        return max(5.0, span / 2.0)
    except Exception:
        return 500.0


class NominatimProvider(Provider):
    name = "nominatim"
    countries = ("*",)
    capabilities = {
        "address": Capability(
            CAP_AVAILABLE,
            "OpenStreetMap worldwide. Density varies by country: "
            "addressed buildings are common in NW Europe and sparse "
            "elsewhere.", LICENCE),
        "parcel": Capability(
            CAP_NONE, "OSM does not hold legal parcel boundaries."),
        "building": Capability(
            CAP_LIMITED, "Footprints come from the Overpass provider, not "
            "from geocoding.", LICENCE),
    }

    def __init__(self, cache=None, session=None):
        self.cache = cache or cache_mod.default()
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict, ttl=30 * 86400):
        key = cache_mod.Cache.key(self.name, path,
                                 json.dumps(params, sort_keys=True))
        hit = self.cache.get(key)
        if hit is not None:
            return hit, True
        self.cache.throttle(self.name, MIN_INTERVAL)
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        r = self.session.get(url, headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        data = r.json()
        self.cache.put(key, self.name, LICENCE, data, ttl=ttl)
        return data, False

    def _prov(self, item, cached: bool, method="as published"):
        osm_id = (f"{item.get('osm_type','')}/{item.get('osm_id','')}"
                  if item.get("osm_id") else None)
        return Provenance(
            source_provider=self.name,
            source_dataset="openstreetmap",
            source_identifier=osm_id,
            licence=LICENCE,
            observation_date=None,   # OSM does not publish a survey date
            accuracy_m=_accuracy(item),
            confidence=min(1.0, float(item.get("importance", 0.4)) + 0.35),
            processing_method=method + (" (cached)" if cached else ""),
        )

    def geocode(self, query: str, *, country=None, limit=5):
        query = (query or "").strip()
        if not query:
            return Missing("empty search", asked=(self.name,))
        params = {"q": query, "format": "jsonv2", "limit": max(1, min(20, limit)),
                  "addressdetails": 1, "polygon_geojson": 1}
        if country:
            params["countrycodes"] = country.lower()
        try:
            data, cached = self._get("/search", params)
        except Exception as e:
            return transport_missing(self.name, "address", e)
        if not data:
            return Missing(
                f"no match for {query!r} in OpenStreetMap",
                asked=(self.name,),
                detail="Try a fuller address, or a postcode with the town.")
        out = []
        for item in data:
            out.append({
                "label": item.get("display_name"),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "type": item.get("addresstype") or item.get("type"),
                "country_code": (item.get("address", {})
                                 .get("country_code", "") or "").upper(),
                "postcode": item.get("address", {}).get("postcode"),
                "bbox": [float(v) for v in item.get("boundingbox", [])] or None,
                # The polygon Nominatim holds for the matched OBJECT. For a
                # building hit this IS the footprint; the property engine
                # prefers Overpass but this saves a round trip.
                "geometry": item.get("geojson"),
                "osm_id": (f"{item.get('osm_type','')}/{item.get('osm_id','')}"
                           if item.get("osm_id") else None),
                "accuracy_m": _accuracy(item),
                "provenance": self._prov(item, cached).as_dict(),
            })
        return sourced(out, self._prov(data[0], cached), CLASS_VERIFIED)

    def reverse(self, lat: float, lon: float):
        params = {"lat": lat, "lon": lon, "format": "jsonv2",
                  "addressdetails": 1, "zoom": 18}
        try:
            item, cached = self._get("/reverse", params)
        except Exception as e:
            return transport_missing(self.name, "address", e)
        if not item or "error" in item:
            return Missing(
                f"no address in OpenStreetMap at {lat:.5f}, {lon:.5f}",
                asked=(self.name,),
                detail="Unaddressed land, or a country where addresses are "
                       "not mapped in OSM.")
        a = item.get("address", {})
        value = {
            "label": item.get("display_name"),
            "house_number": a.get("house_number"),
            "road": a.get("road"),
            "postcode": a.get("postcode"),
            "city": a.get("city") or a.get("town") or a.get("village"),
            "country": a.get("country"),
            "country_code": (a.get("country_code", "") or "").upper(),
            "lat": float(item["lat"]), "lon": float(item["lon"]),
        }
        return sourced(value, self._prov(item, cached), CLASS_VERIFIED)
