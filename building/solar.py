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
    # twice. Live, that turned a 278 m2 roof into 406 m2 — a 46%
    # over-order, on the one number this module exists to get right.
    footprint = round(building.get("groundAreaMeters2") or 0, 2) or None
    roof_ground = round(whole.get("groundAreaMeters2") or 0, 2) or None

    # A degenerate segment — zero area, or one rounded to zero — must not take
    # the job down. Weighting by area divides by the total, and a response
    # whose only pitched plane has no area made that a ZeroDivisionError on
    # the whole roof job, for a plane that contributes nothing anyway.
    pitched = [p for p in planes if not p["flat"] and p["sloped_area_m2"] > 0]
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
        # ALL THREE PARTS OR NO DATE. Gating on year alone let a partial
        # imageryDate ({"year": 2023}, month/day absent or null) reach the
        # :02d format with None and raise TypeError — killing a roof job
        # whose free LIDAR path had already finished. A partial date is not
        # a date; report None rather than fabricate a "-None-" string.
        "imagery_date": (
            f"{date.get('year')}-{date.get('month'):02d}-"
            f"{date.get('day'):02d}"
            if all(isinstance(date.get(k), int)
                   for k in ("year", "month", "day")) else None),
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
        # badly on a real one. A real pub roof has 12 segments, the largest only 18%
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
    # covers the whole building. On a real pub roof that is 277.81 against 308.01,
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


def measure_heights(lat, lon, radius_m=30):
    """Real eaves and ridge heights, from Solar's own elevation model.

    An audit found the flagship mode assuming 2.75m storeys while this module
    was already authenticated to the endpoint that measures the answer: the
    dataLayers DSM is a ~10cm surface model, and its building mask says
    which pixels are roof. Ridge = the highest masked pixel; ground = the
    median of the UNmasked pixels around the building, which is the garden
    and the road. Both are ortho heights, so their difference is the
    building's own height above its ground — no geoid gymnastics required.

    Returns {ground_od_m, ridge_od_m, ridge_agl_m, source} or None, and
    never raises: a worker without tifffile, or a site without DSM
    coverage, falls back to the assumption it would have used anyway — the
    caller's provenance says which happened.
    """
    key = api_key()
    if not key:
        return None
    try:
        import io
        import numpy as np
        import tifffile
        import requests
        r = requests.get("https://solar.googleapis.com/v1/dataLayers:get",
                         params={"location.latitude": lat,
                                 "location.longitude": lon,
                                 "radiusMeters": radius_m,
                                 # DSM_LAYER alone omits maskUrl (verified
                                 # live); FULL_LAYERS carries both, and only
                                 # the two files needed are ever downloaded.
                                 "view": "FULL_LAYERS",
                                 "requiredQuality": "MEDIUM", "key": key},
                         timeout=60)
        if r.status_code != 200:
            return None
        body = r.json()
        out = {}
        for name, url_key in (("dsm", "dsmUrl"), ("mask", "maskUrl")):
            url = body.get(url_key)
            if not url:
                return None
            g = requests.get(url, params={"key": key}, timeout=120)
            g.raise_for_status()
            # PIL mangles float GeoTIFF tiles; tifffile does not. Learned
            # live on this exact layer earlier in the project.
            out[name] = tifffile.imread(io.BytesIO(g.content))
        dsm, mask = out["dsm"].astype("float64"), out["mask"]
        if mask.shape != dsm.shape:
            return None
        valid = np.abs(dsm) < 1e4          # nodata in this layer is ~3.4e38
        roof = (mask > 0) & valid
        ground = (mask == 0) & valid
        if roof.sum() < 25 or ground.sum() < 100:
            return None
        ground_od = float(np.median(dsm[ground]))
        # 99.5th percentile, not max: a single hot pixel on an aerial or a
        # chimney pot must not set the ridge for the whole model.
        ridge_od = float(np.percentile(dsm[roof], 99.5))
        agl = ridge_od - ground_od
        if not 2.0 <= agl <= 20.0:
            return None
        return {"ground_od_m": round(ground_od, 2),
                "ridge_od_m": round(ridge_od, 2),
                "ridge_agl_m": round(agl, 2),
                "source": "Google Solar dataLayers DSM + building mask"}
    except Exception as e:
        import sys as _sys
        print(f"solar height measurement unavailable: "
              f"{type(e).__name__}: {e}", file=_sys.stderr)
        return None


def surface_grid(lat, lon, radius_m=25):
    """The DSM height field with its georeferencing, for footprint work.

    measure_heights() boils the same two files down to one ridge number;
    this keeps the grids, because the mask + heights together draw the
    building's TRUE present-day footprint — including the flat-roofed
    additions that OpenStreetMap has never heard of. At 3 Basons Lane the
    mapped outline is the original 1930s pair; the mask shows the single-
    storey front and side additions the owner actually built, as a clean
    2-4m height band.

    Returns {agl, ground_od_m, utm_epsg, transform} or None; agl is a
    float array (metres above ground, NaN where unmasked/invalid) and
    transform maps pixel (row, col) -> (easting, northing) in utm_epsg:
    E = ox + sx*col, N = oy + sy*row.
    """
    key = api_key()
    if not key:
        return None
    try:
        import io
        import numpy as np
        import tifffile
        import requests
        r = requests.get("https://solar.googleapis.com/v1/dataLayers:get",
                         params={"location.latitude": lat,
                                 "location.longitude": lon,
                                 "radiusMeters": radius_m,
                                 "view": "FULL_LAYERS",
                                 "requiredQuality": "MEDIUM", "key": key},
                         timeout=60)
        if r.status_code != 200:
            return None
        body = r.json()
        grids, transform, epsg = {}, None, None
        for name, url_key in (("dsm", "dsmUrl"), ("mask", "maskUrl")):
            url = body.get(url_key)
            if not url:
                return None
            g = requests.get(url, params={"key": key}, timeout=120)
            g.raise_for_status()
            tf = tifffile.TiffFile(io.BytesIO(g.content))
            page = tf.pages[0]
            grids[name] = page.asarray()
            tags = {t.name: t.value for t in page.tags}
            tr = tags.get("ModelTransformationTag")
            gk = tags.get("GeoKeyDirectoryTag")
            if tr and transform is None:
                # (sx, 0, 0, ox, 0, sy, 0, oy, ...)
                transform = (tr[0], tr[3], tr[5], tr[7])
            if gk and epsg is None:
                # GeoKey quads: (id, location, count, value); 3072 = CRS
                for i in range(0, len(gk) - 3, 4):
                    if gk[i] == 3072:
                        epsg = int(gk[i + 3])
        dsm = grids["dsm"].astype("float64")
        mask = grids["mask"]
        if mask.shape != dsm.shape or transform is None or not epsg:
            return None
        valid = np.abs(dsm) < 1e4
        ground = (mask == 0) & valid
        if ground.sum() < 100 or ((mask > 0) & valid).sum() < 25:
            return None
        ground_od = float(np.median(dsm[ground]))
        agl = np.where((mask > 0) & valid, dsm - ground_od, np.nan)
        return {"agl": agl, "ground_od_m": round(ground_od, 2),
                "utm_epsg": epsg, "transform": transform,
                "source": "Google Solar dataLayers DSM + building mask"}
    except Exception as e:
        import sys as _sys
        print(f"solar surface grid unavailable: "
              f"{type(e).__name__}: {e}", file=_sys.stderr)
        return None
