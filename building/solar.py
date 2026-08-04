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
    building = potential.get("buildingStats") or {}
    whole = potential.get("wholeRoofStats") or {}

    # THE FOOTPRINT IS groundAreaMeters2, NOT areaMeters2.
    #
    # Solar reports both, and they are not the same thing: areaMeters2 is the
    # roof's SURFACE, already inflated by the pitch, while groundAreaMeters2
    # is its shadow on the ground. Reading the surface as a footprint and
    # then dividing by cos(pitch) — which compare() does — applies the slope
    # twice. Live on The Vine that turned a 278 m2 roof into 406 m2: a 46%
    # over-order, on the one number this module exists to get right.
    footprint = round(building.get("groundAreaMeters2") or 0, 2) or None
    roof_ground = round(whole.get("groundAreaMeters2") or 0, 2) or None

    pitched = [p for p in planes if not p["flat"]]
    weighted = median = spread = None
    if pitched:
        total = sum(p["sloped_area_m2"] for p in pitched)
        weighted = round(
            sum(p["pitch_deg"] * p["sloped_area_m2"] for p in pitched)
            / total, 1)
        ordered = sorted(pitched, key=lambda p: p["pitch_deg"])
        # Area-weighted median: walk the segments in pitch order until half
        # the roof is behind you. On a roof with a few steep outliers this
        # is the number a roofer would recognise; the mean is not.
        run = 0.0
        for p in ordered:
            run += p["sloped_area_m2"]
            if run >= total / 2:
                median = p["pitch_deg"]
                break
        spread = round(ordered[-1]["pitch_deg"] - ordered[0]["pitch_deg"], 1)

    return {
        "source": "google_solar",
        "quality": payload.get("imageryQuality"),
        "imagery_date": (f"{date.get('year')}-{date.get('month'):02d}-"
                         f"{date.get('day'):02d}"
                         if date.get("year") else None),
        "footprint_m2": footprint,
        "roof_ground_area_m2": roof_ground,
        # Kept under its old name because roof.py and the tests read it, but
        # it is now unambiguously the roof SURFACE, not a plan area.
        "building_area_m2": round(building.get("areaMeters2") or 0, 2) or None,
        "whole_roof_area_m2": round(whole.get("areaMeters2") or 0, 2) or None,
        "planes": planes,
        "segments": len(planes),
        "sloped_area_m2": round(sum(p["sloped_area_m2"] for p in planes), 2),
        "plan_area_m2": round(sum(p["plan_area_m2"] for p in planes), 2),
        # PITCH IS AREA-WEIGHTED, NOT THE BIGGEST SEGMENT.
        #
        # Picking the largest single plane works on a simple roof and fails
        # badly on a real one. The Vine has 12 segments; the largest is 18%
        # of the area and sits at 57.8 degrees — a dormer cheek or a gable,
        # not the roof. It was reported as the pitch, 17 degrees above the
        # weighted mean and 24 above what the height model shows.
        "predominant_pitch_deg": median,
        "mean_pitch_deg": weighted,
        "pitch_spread_deg": spread,
        # A roof this varied is not one pitch, and a single figure taken off
        # it should be treated as indicative rather than as a measurement.
        "complex": bool(spread is not None and spread >= 15.0),
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
    # groundAreaMeters2, not areaMeters2 — see parse_segments. Falls back to
    # the roof's own ground area, then to nothing, rather than silently
    # comparing a plan area against a sloped one.
    sa = (solar_result.get("footprint_m2")
          or solar_result.get("roof_ground_area_m2"))
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
    # THE FULL ROOF IS buildingStats.areaMeters2.
    #
    # Solar publishes two surface areas and one is a subset of the other:
    # wholeRoofStats covers the part it broke into segments, buildingStats
    # covers the whole building. On The Vine that is 277.81 against 308.01,
    # and the sum of the twelve segments reproduces the first exactly.
    #
    # An earlier fix here read buildingStats as a FOOTPRINT, decided that a
    # 93.6 m2 roof over a 116.6 m2 footprint was "physically impossible for a
    # 35 degree roof", and built a workaround on that. It was a surface
    # against a surface all along, and a subset being smaller than its
    # superset is not a paradox. The workaround — footprint / cos(pitch) —
    # is kept only for responses that carry no measured area at all.
    ls = lidar_quantities.get("sloped_area_m2")
    measured = (solar_result.get("building_area_m2")
                or solar_result.get("whole_roof_area_m2"))
    if ls and measured:
        out["sloped_area_m2"] = {
            "lidar": ls,
            "solar_measured": measured,
            "solar_segmented": solar_result.get("whole_roof_area_m2"),
            "delta_pct": round((ls - measured) / measured * 100, 1),
            "basis": "solar buildingStats.areaMeters2 — the whole roof "
                     "surface as measured, not derived from a pitch. "
                     "solar_segmented is the part Solar broke into planes "
                     "and is a subset of it.",
        }
    elif ls and sa and sp is not None:
        import math
        implied = sa / math.cos(math.radians(sp))
        out["sloped_area_m2"] = {
            "lidar": ls,
            "solar_implied": round(implied, 2),
            "solar_analysed": solar_result.get("sloped_area_m2"),
            "delta_pct": round((ls - implied) / implied * 100, 1),
            "basis": "solar FOOTPRINT / cos(solar pitch), used only where "
                     "Solar reports no measured roof area",
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
    if solar_result.get("complex"):
        notes.append(
            f"This roof is {solar_result.get('segments')} planes spanning "
            f"{solar_result.get('pitch_spread_deg')} degrees of pitch — it is "
            f"not one roof at one angle. A single pitch figure is indicative "
            f"only; measure the range you are actually working on.")
    out["notes"] = notes
    return out
