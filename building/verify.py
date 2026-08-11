"""Confirm the right building BEFORE modelling it — from independent sources.

THE RULE THIS ENFORCES: "if you can't locate the correct house don't
hallucinate, verify before each task." A single geocoder can land on the
wrong house (a postcode centroid picked a house four doors away earlier in
this project). The defence is agreement: ask several sources that do not
share a failure mode, and only proceed when they cluster on one building.

FOUR INDEPENDENT LEGS, each verified live against 3 Basons Lane:

  street view   metadata geocodes the address string -> a camera position
                and an imagery date. Google's road geocoder.
  postcode      postcodes.io returns the postcode centroid. A different
                geocoder, different data (ONS), so it fails differently.
  solar         buildingInsights finds the nearest BUILDING with a roof and
                returns its centre and footprint area — proof a building
                actually stands at the point, not just that the point exists.
  web           a property search (Rightmove/Zoopla/EPC) describes the house
                in words: "3-bed semi-detached, corner plot". This confirms
                the TYPE the model derived (semi vs detached vs terrace),
                which the geocoders cannot. Needs a search provider, so it is
                optional and pluggable — pass a `search` callable.

THE VERDICT is agreement, in metres. When the geocoders and the building
centre fall within CONFIRM_M of each other they name one house and the job
proceeds. When they spread past CONFLICT_M they name different houses and
the job must stop and ask, not guess — that is the whole point.

Nothing here raises for a missing source: with only one leg answering, the
report says so and the verdict is UNCONFIRMED, never a false CONFIRMED.
"""
import math
import os
import sys
from urllib.parse import quote


CONFIRM_M = 30.0     # within this, the sources name one building
CONFLICT_M = 60.0    # beyond this, they name different buildings — stop

SV_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
SOLAR_BI = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
POSTCODES = "https://api.postcodes.io/postcodes/"


def _key():
    return os.environ.get("GOOGLE_SOLAR_API_KEY") or \
        os.environ.get("GOOGLE_AI_API_KEY") or ""


def _get(url, params=None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=20,
                         headers={"User-Agent": "building-verify/1.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"verify: {type(e).__name__} on {url[:50]}", file=sys.stderr)
        return None


def _metres(a, b):
    """Great-circle-ish distance in metres between two (lat, lon)."""
    return math.hypot((b[0] - a[0]) * 111320.0,
                      (b[1] - a[1]) * 111320.0 * math.cos(math.radians(a[0])))


def street_view(address, key):
    d = _get(SV_META, {"location": address, "source": "outdoor", "key": key})
    if not d or d.get("status") != "OK":
        return None
    loc = d.get("location") or {}
    if loc.get("lat") is None:
        return None
    return {"lat": loc["lat"], "lon": loc["lng"], "imagery_date": d.get("date")}


def postcode_point(postcode):
    if not postcode:
        return None
    d = _get(POSTCODES + quote(postcode.replace(" ", "")))
    if not d or d.get("status") != 200:
        return None
    r = d["result"]
    return {"lat": r["latitude"], "lon": r["longitude"],
            "ward": r.get("admin_ward"), "district": r.get("admin_district")}


def solar_building(lat, lon, key):
    d = _get(SOLAR_BI, {"location.latitude": lat, "location.longitude": lon,
                        "requiredQuality": "MEDIUM", "key": key})
    if not d or "center" not in d:
        return None
    c = d["center"]
    area = ((d.get("solarPotential") or {}).get("wholeRoofStats") or {}) \
        .get("groundAreaMeters2")
    return {"lat": c["latitude"], "lon": c["longitude"],
            "roof_area_m2": round(area, 1) if area else None,
            "imagery_date": d.get("imageryDate")}


def cross_check(address=None, postcode=None, gps=None, search=None, key=None):
    """Locate the building from every available source and score agreement.

    `search` is an optional callable(address_or_postcode) -> str, a live web
    search whose text is scanned for the dwelling type. Returns a report with
    a `verdict` of CONFIRMED / UNCONFIRMED / CONFLICT and every source's
    point, so a caller can show its work and a human can adjudicate a split.
    """
    key = key or _key()
    points, report = {}, {"sources": {}}

    if (address or postcode) and key:
        sv = street_view(address or postcode, key)
        if sv:
            points["street_view"] = (sv["lat"], sv["lon"])
            report["sources"]["street_view"] = sv

    pc = postcode_point(postcode)
    if pc:
        points["postcode"] = (pc["lat"], pc["lon"])
        report["sources"]["postcode"] = pc

    # Solar needs a seed point; use whatever geocode we already have, or gps.
    seed = None
    if gps and gps.get("lat") is not None:
        seed = (gps["lat"], gps["lon"])
        points["gps"] = seed
    elif points:
        seed = next(iter(points.values()))
    if seed and key:
        sb = solar_building(seed[0], seed[1], key)
        if sb:
            points["solar_building"] = (sb["lat"], sb["lon"])
            report["sources"]["solar_building"] = sb

    if search and (address or postcode):
        try:
            text = (search(address or postcode) or "").lower()
            kinds = [k for k in ("semi-detached", "detached", "terraced",
                                 "end of terrace", "end-terrace", "flat",
                                 "bungalow") if k in text]
            beds = None
            import re
            m = re.search(r"(\d+)\s*[- ]?bed", text)
            if m:
                beds = int(m.group(1))
            report["sources"]["web"] = {
                "dwelling_type": kinds[0] if kinds else None,
                "bedrooms": beds,
                "found": bool(kinds or beds)}
        except Exception as e:
            report["sources"]["web"] = {"error": type(e).__name__}

    report["located_by"] = list(points)
    verdict, spread, message = agreement(points)
    report["max_spread_m"] = round(spread, 1)
    report["verdict"] = verdict
    report["message"] = message
    return report


# THE POSTCODE CENTROID IS THE WEAK LEG, AND MUST NOT SINK A GOOD MATCH. It
# is a street/unit centroid, not a building — on a corner plot it sits tens
# of metres off the house while the building-level sources agree tightly.
# Judging on the widest gap of ALL points let the postcode alone push a
# correct house to UNCONFIRMED (Basons: building sources 3m apart, postcode
# 30m out, raw spread 36m). So agreement is judged on the BUILDING-LEVEL
# sources — Street View's building geocode, the caller's gps, Solar's roof —
# and the postcode is a consistency note, not a vote. Widening the threshold
# to make the postcode fit would be fitting the rule to one answer; excluding
# the leg that is known to be coarse is the honest fix.
BUILDING_LEVEL = ("street_view", "gps", "solar_building")


def agreement(points):
    """(verdict, max_spread_m, message) from located source points.

    points: {source_name: (lat, lon)}. Pure — no network — so the verdict
    thresholds are testable without a live key.
    """
    building = [(k, v) for k, v in points.items() if k in BUILDING_LEVEL]
    judged = building if len(building) >= 2 else list(points.items())
    locs = [v for _, v in judged]
    spread = 0.0
    for i in range(len(locs)):
        for j in range(i + 1, len(locs)):
            spread = max(spread, _metres(locs[i], locs[j]))
    n = len(locs)
    names = [k for k, _ in judged]

    if n == 0:
        return "UNLOCATABLE", 0.0, ("No source could place this address. "
                                    "Check the address and postcode.")
    if n == 1:
        return "UNCONFIRMED", 0.0, (
            f"Only {names[0]} answered — one source cannot confirm a house. "
            f"Proceeding is a guess; add a postcode or gps.")
    if spread <= CONFIRM_M:
        return "CONFIRMED", spread, (
            f"{n} independent building-level sources agree within "
            f"{spread:.0f}m — this is one building.")
    if spread <= CONFLICT_M:
        return "UNCONFIRMED", spread, (
            f"{n} sources span {spread:.0f}m — they may be the same building "
            f"or its neighbour. Confirm with a photo or gps before modelling.")
    return "CONFLICT", spread, (
        f"{n} sources span {spread:.0f}m — they name DIFFERENT buildings. Do "
        f"not model until this is resolved; pass gps for the house itself.")
