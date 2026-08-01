"""Google Solar API — roof geometry, and ground truth for the LIDAR path.

The Solar API's buildingInsights endpoint returns per-segment roof pitch,
azimuth and area, derived from imagery far finer than the 1m open LIDAR.
That makes it useful twice over: as a better primary source where it has
coverage, and as an independent check on the free path.

It is NOT the default. Open LIDAR covers ~99% of England for nothing,
while this is metered per request and needs a billing-enabled key. So it
runs when a key is configured, and the free path runs otherwise.

THE KEY IS NEVER STORED IN CODE. It is read from the environment, exactly
as SUPABASE_KEY is — set GOOGLE_SOLAR_API_KEY on the endpoint.
"""
import os
import sys

SOLAR_ENDPOINT = os.environ.get(
    "GOOGLE_SOLAR_ENDPOINT",
    "https://solar.googleapis.com/v1/buildingInsights:findClosest")
HTTP_TIMEOUT = 45

# Solar grades its own output. MEDIUM and LOW come from coarser imagery and
# are not obviously better than the LIDAR path, so only HIGH is treated as
# ground truth for cross-checking.
TRUSTED_QUALITY = ("HIGH",)


def api_key():
    """The configured key, or None. Never hard-coded, never logged."""
    return os.environ.get("GOOGLE_SOLAR_API_KEY") or None


def available():
    return bool(api_key())


def fetch_building_insights(lat, lon, quality="HIGH"):
    """Roof geometry for the building nearest a point, or None.

    Returns None rather than raising: Solar is an enhancement, and a missing
    key, a metering limit or a location outside coverage must never take
    down a job the free path could have completed.
    """
    key = api_key()
    if not key:
        return None

    import requests
    try:
        r = requests.get(
            SOLAR_ENDPOINT,
            params={"location.latitude": lat, "location.longitude": lon,
                    "requiredQuality": quality, "key": key},
            headers={"User-Agent": "building-scan/1.0"},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        print(f"solar: request failed: {type(e).__name__}", file=sys.stderr)
        return None

    if r.status_code == 404:
        # Genuinely common: coverage is not universal.
        print("solar: no building found at this location", file=sys.stderr)
        return None
    if r.status_code != 200:
        # Deliberately does NOT echo the response body — an auth error can
        # quote the key back, and this goes to shared worker logs.
        print(f"solar: HTTP {r.status_code}", file=sys.stderr)
        return None

    try:
        return r.json()
    except Exception:
        return None


def parse_segments(payload):
    """Normalise buildingInsights into the shape the rest of Roof Mode uses.

    Azimuth and our aspect are the same convention — compass bearing of the
    downslope direction, 0 = north — which is what made the two comparable
    without transformation when this was validated.
    """
    if not payload:
        return None

    potential = payload.get("solarPotential") or {}
    segments = potential.get("roofSegmentStats") or []
    if not segments:
        return None

    planes = []
    for s in segments:
        pitch = s.get("pitchDegrees")
        area = (s.get("stats") or {}).get("areaMeters2")
        if pitch is None or area is None:
            continue
        # Solar reports the SLOPED area of each segment; plan area is that
        # foreshortened by the pitch. Getting this backwards would inflate
        # every quantity downstream.
        import math
        plan = area * math.cos(math.radians(pitch))
        planes.append({
            "pitch_deg": round(pitch, 1),
            "aspect_deg": (round(s["azimuthDegrees"], 1)
                           if s.get("azimuthDegrees") is not None else None),
            "sloped_area_m2": round(area, 2),
            "plan_area_m2": round(plan, 2),
            "flat": pitch < 5.0,
        })

    if not planes:
        return None

    date = payload.get("imageryDate") or {}
    return {
        "source": "google_solar",
        "quality": payload.get("imageryQuality"),
        "imagery_date": (f"{date.get('year')}-{date.get('month'):02d}-"
                         f"{date.get('day'):02d}"
                         if date.get("year") else None),
        "building_area_m2": round(
            (potential.get("buildingStats") or {}).get("areaMeters2", 0), 2)
        or None,
        "whole_roof_area_m2": round(
            (potential.get("wholeRoofStats") or {}).get("areaMeters2", 0), 2)
        or None,
        "planes": planes,
        "sloped_area_m2": round(sum(p["sloped_area_m2"] for p in planes), 2),
        "plan_area_m2": round(sum(p["plan_area_m2"] for p in planes), 2),
        "predominant_pitch_deg": max(
            (p for p in planes if not p["flat"]),
            key=lambda p: p["sloped_area_m2"], default={}).get("pitch_deg"),
    }


def compare(lidar_quantities, solar_result):
    """Cross-check the free path against Solar, and say where they differ.

    The point is not to pick a winner but to surface disagreement. Two
    independent sources agreeing is worth stating on a quote; two sources
    3 degrees apart is worth knowing before ordering tiles.
    """
    if not solar_result:
        return None

    out = {"solar_quality": solar_result.get("quality"),
           "solar_imagery_date": solar_result.get("imagery_date")}

    lp = lidar_quantities.get("predominant_pitch_deg")
    sp = solar_result.get("predominant_pitch_deg")
    if lp is not None and sp is not None:
        out["pitch_deg"] = {"lidar": lp, "solar": sp,
                            "delta": round(sp - lp, 1)}

    la = lidar_quantities.get("plan_area_m2")
    sa = solar_result.get("building_area_m2")
    if la and sa:
        out["plan_area_m2"] = {
            "lidar": la, "solar": sa,
            "delta_pct": round((la - sa) / sa * 100, 1)}

    # Sloped area needs care. Solar's roofSegmentStats cover only the roof it
    # ANALYSED for panel placement, so their sum is routinely smaller than
    # the real roof — live-confirmed at 93.6 m2 against a 116.6 m2 footprint,
    # which is physically impossible for a 35-degree roof, where the sloped
    # area must EXCEED the footprint. Comparing our full roof against that
    # partial figure produced a 48% false alarm.
    #
    # The sound comparison derives Solar's implied full roof from its own
    # footprint and pitch: area = footprint / cos(pitch).
    ls = lidar_quantities.get("sloped_area_m2")
    if ls and sa and sp is not None:
        import math
        implied = sa / math.cos(math.radians(sp))
        out["sloped_area_m2"] = {
            "lidar": ls,
            "solar_implied": round(implied, 2),
            "solar_analysed": solar_result.get("sloped_area_m2"),
            "delta_pct": round((ls - implied) / implied * 100, 1),
            "basis": "solar footprint / cos(solar pitch); solar_analysed is "
                     "panel-suitable roof only and is not the full area",
        }

    notes = []
    pitch_delta = (out.get("pitch_deg") or {}).get("delta")
    if pitch_delta is not None and abs(pitch_delta) >= 2.0:
        notes.append(
            f"Pitch sources disagree by {pitch_delta:+.1f} degrees "
            f"(LIDAR {lp}, Solar {sp}). Solar uses finer imagery and is the "
            f"better estimate where its quality is HIGH.")
    area_delta = (out.get("sloped_area_m2") or {}).get("delta_pct")
    if area_delta is not None and abs(area_delta) >= 10.0:
        notes.append(
            f"Sloped area sources disagree by {area_delta:+.1f}%. Check the "
            f"footprint covers the same building.")
    out["notes"] = notes
    return out
