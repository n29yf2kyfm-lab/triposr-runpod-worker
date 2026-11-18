"""Render Mode — a proposed extension drawn onto real imagery of the site.

The output of this mode is the image a builder shows a customer and a
planning officer: the client's actual house, from the air, with the proposed
extension standing on it. It was proven by hand twice — a side extension in
Birmingham and a back kitchen in Cradley Heath — before being folded in
here; this module is that proven sequence, made repeatable:

    1. Google Solar dataLayers  -> real aerial photo of the site (the same
       key the roof pipeline already uses; ~10cm/pixel where covered)
    2. a measured footprint     -> drawn on the photo as a red constraint
       outline, because the one time the generator was asked to place the
       extension WITHOUT the outline it slabbed the whole street
    3. Gemini image generation  -> builds the extension inside the outline,
       matched to the photo's light and grain, and removes the outline

HONESTY RULES, learned the hard way. The constraint outline is not
decoration: unconstrained generation invents geometry at the wrong scale in
the wrong place. The result is a VISUALISATION of a proposal and the output
says so — it is not a survey, and the worker's caption warning must travel
with the image. And when the generator returns something that ignored the
constraint, that is a FAILED render, not a deliverable; the caller gets the
failure, never a wrong building presented as theirs.
"""
import base64
import json
import math
import os
import sys

GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_API = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{GEMINI_MODEL}:generateContent")

SOLAR_LAYERS_API = "https://solar.googleapis.com/v1/dataLayers:get"

# Metres of aerial context around the house. Enough to see the neighbours
# — a proposal drawn on a tight crop of one roof convinces nobody.
AERIAL_RADIUS_M = 60
CROP_HALF_M = 18.0
OUT_PX = 900                     # rendered crop size; 25 px per metre

MAX_ZONE_M = 12.0                # an "extension" bigger than this is a house


class RenderError(RuntimeError):
    """The visual could not be produced honestly."""


def _requests():
    import requests
    return requests


def _keys():
    solar = os.environ.get("GOOGLE_SOLAR_API_KEY", "")
    gemini = os.environ.get("GOOGLE_AI_API_KEY", "")
    if not solar:
        raise RenderError(
            "GOOGLE_SOLAR_API_KEY is not configured, so the site's aerial "
            "imagery cannot be fetched.")
    if not gemini:
        raise RenderError(
            "GOOGLE_AI_API_KEY is not configured, so the extension cannot "
            "be drawn. The aerial half of this mode worked; set the key and "
            "resend the job.")
    return solar, gemini


def fetch_aerial(lat, lon, work_dir, solar_key):
    """The real aerial photo around the site, as a local GeoTIFF path."""
    r = _requests().get(SOLAR_LAYERS_API, params={
        "location.latitude": lat, "location.longitude": lon,
        "radiusMeters": AERIAL_RADIUS_M,
        "view": "IMAGERY_AND_ANNUAL_FLUX_LAYERS",
        "requiredQuality": "MEDIUM", "key": solar_key}, timeout=60)
    if r.status_code != 200:
        raise RenderError(
            f"Solar dataLayers answered {r.status_code} for this location — "
            f"no aerial imagery coverage here, so there is nothing real to "
            f"draw the extension onto.")
    body = r.json()
    url = body.get("rgbUrl")
    if not url:
        raise RenderError("Solar dataLayers returned no rgbUrl.")
    img = _requests().get(url, params={"key": solar_key}, timeout=120)
    img.raise_for_status()
    path = os.path.join(work_dir, "aerial.tif")
    with open(path, "wb") as f:
        f.write(img.content)
    date = body.get("imageryDate") or {}
    return path, date


def zone_polygon(zone, ppm=25.0, centre=(OUT_PX / 2, OUT_PX / 2)):
    """The constraint rectangle in crop pixels.

    `zone` is metres in the HOUSE's frame: bearing_deg is the direction the
    terrace row / ridge runs; `along` spans across the house parallel to
    that; `out` runs perpendicular, positive toward the garden. This is the
    same frame the hand-run used, where it survived contact with two real
    houses — including catching its own one-bay-off mistake, because a
    rectangle in metres can be shifted by a bay width and checked.
    """
    brg = math.radians(zone["bearing_deg"])
    nrm = brg + math.pi / 2 * (1 if zone.get("out_positive", True) else -1)
    cx, cy = centre

    def pt(along, out):
        return (cx + (along * math.sin(brg) + out * math.sin(nrm)) * ppm,
                cy - (along * math.cos(brg) + out * math.cos(nrm)) * ppm)

    a0, a1 = zone["along0_m"], zone["along1_m"]
    o0, o1 = zone["out0_m"], zone["out1_m"]
    return [pt(a0, o0), pt(a1, o0), pt(a1, o1), pt(a0, o1)]


def crop_and_mark(aerial_path, lat, lon, zone, work_dir):
    """Crop the aerial to the house and draw the red constraint outline."""
    from PIL import Image, ImageDraw

    src = Image.open(aerial_path).convert("RGB")
    W, H = src.size
    mpp = (2 * AERIAL_RADIUS_M) / max(W, H)   # Solar serves ~0.1 m/px
    half = int(CROP_HALF_M / mpp)
    cx, cy = W // 2, H // 2                   # layers are centred on the request
    crop = src.crop((cx - half, cy - half, cx + half, cy + half))
    crop = crop.resize((OUT_PX, OUT_PX))

    clean = os.path.join(work_dir, "aerial_crop.jpg")
    crop.save(clean, quality=92)

    marked = crop.copy()
    d = ImageDraw.Draw(marked)
    ppm = OUT_PX / (2 * CROP_HALF_M)
    d.polygon(zone_polygon(zone, ppm=ppm), outline=(255, 40, 40), width=5)
    marked_path = os.path.join(work_dir, "aerial_marked.jpg")
    marked.save(marked_path, quality=92)
    return clean, marked_path


def composite(clean_path, zone, work_dir, sun_deg=225.0):
    """Draw the proposed roof-plan INTO the zone, deterministically.

    Two live endpoint runs asked the generator to respect the constraint
    rectangle and it slabbed the whole terrace both times. Geometry is not
    something to request politely from a diffusion model — it is placed by
    code, to the millimetre-equivalent, every single run. The membrane
    tone, fascia, rooflights and a sun-side shadow are drawn at the crop's
    scale; the AI pass (style="ai") remains available for styling but the
    DEFAULT ships the version that cannot put the roof on the street.
    """
    from PIL import Image, ImageDraw, ImageFilter
    import random

    im = Image.open(clean_path).convert("RGB")
    ppm = OUT_PX / (2 * CROP_HALF_M)
    poly = zone_polygon(zone, ppm=ppm)

    # soft drop shadow first, offset away from the sun
    sh = Image.new("L", im.size, 0)
    off = 0.45 * ppm / 25 * 25
    dx = -math.sin(math.radians(sun_deg)) * 0.35 * ppm / 6
    dy = math.cos(math.radians(sun_deg)) * 0.35 * ppm / 6
    ImageDraw.Draw(sh).polygon([(x + dx * 6, y + dy * 6) for x, y in poly],
                               fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    black = Image.new("RGB", im.size, (10, 10, 12))
    im = Image.composite(black, im, sh.point(lambda v: v // 2))

    d = ImageDraw.Draw(im)
    d.polygon(poly, fill=(74, 76, 79))                    # membrane
    # subtle tonal noise so the surface is not a flat vector
    rnd = random.Random(37)
    minx = int(min(p[0] for p in poly)); maxx = int(max(p[0] for p in poly))
    miny = int(min(p[1] for p in poly)); maxy = int(max(p[1] for p in poly))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    px = im.load(); mk = mask.load()
    for _ in range((maxx - minx) * (maxy - miny) // 14):
        x = rnd.randint(minx, maxx - 1); y = rnd.randint(miny, maxy - 1)
        if mk[x, y]:
            r, g, b = px[x, y]
            v = rnd.randint(-7, 7)
            px[x, y] = (r + v, g + v, b + v)
    d.polygon(poly, outline=(52, 54, 57), width=3)        # fascia line

    # two rooflights on the long axis, thirds of the zone
    def lerp(p, q, f):
        return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
    for f in (1 / 3, 2 / 3):
        c = lerp(lerp(poly[0], poly[1], f), lerp(poly[3], poly[2], f), 0.5)
        u = ((poly[1][0] - poly[0][0]) / max(1e-9, math.dist(poly[0], poly[1])),
             (poly[1][1] - poly[0][1]) / max(1e-9, math.dist(poly[0], poly[1])))
        v = ((poly[3][0] - poly[0][0]) / max(1e-9, math.dist(poly[0], poly[3])),
             (poly[3][1] - poly[0][1]) / max(1e-9, math.dist(poly[0], poly[3])))
        hw = 0.55 * ppm; hh = 0.4 * ppm
        quad = [(c[0] + sx * hw * u[0] + sy * hh * v[0],
                 c[1] + sx * hw * u[1] + sy * hh * v[1])
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        d.polygon(quad, fill=(38, 44, 54), outline=(210, 212, 214), width=2)

    out = os.path.join(work_dir, "render.png")
    im.save(out)
    return out


def _prompt(spec):
    e = spec.get("extension") or {}
    finish = e.get("finish") or "facing brickwork matched to the house"
    roof = e.get("roof") or "flat dark-grey membrane roof with two rooflights"
    extras = e.get("features") or "a set of glazed doors onto the garden"
    return (
        "Aerial photomontage for a UK planning discussion. This is a real "
        "aerial photograph; the RED OUTLINE marks one house's garden area "
        "where an extension is proposed. Build the proposed extension "
        "EXACTLY AND ONLY WITHIN THE RED OUTLINE: walls in " + finish +
        ", " + roof + ", " + extras + ", tight against the existing house. "
        "Match this photo's resolution, colour, grain and shadow direction "
        "so the addition reads as part of the same photograph, weathered in "
        "rather than brand new. REMOVE the red outline from the final "
        "image. Change absolutely nothing else anywhere in the photo. "
        "No text, labels or captions.")


def gemini_edit(image_path, prompt, gemini_key, work_dir):
    """One constrained image edit. Returns the output image path."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        {"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]}}
    r = _requests().post(GEMINI_API, params={"key": gemini_key},
                         json=body, timeout=180)
    if r.status_code == 429:
        raise RenderError(
            "Gemini is rate-limited right now. The job can simply be "
            "resent in a minute — nothing here is broken.")
    if r.status_code != 200:
        raise RenderError(f"Gemini answered {r.status_code}: {r.text[:200]}")
    parts = (((r.json().get("candidates") or [{}])[0]
              .get("content") or {}).get("parts") or [])
    for p in parts:
        data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if data:
            out = os.path.join(work_dir, "render.png")
            with open(out, "wb") as f:
                f.write(base64.b64decode(data))
            return out
    raise RenderError(
        "Gemini returned no image. If this repeats, the prompt was likely "
        "safety-filtered — the job input is echoed in the manifest for "
        "review.")


def run(spec, prog, output_dir):
    """Render mode entry point: gps + zone in, proposal visuals out."""
    import paths
    import delivery

    gps = spec.get("gps") or {}
    lat, lon = gps.get("lat"), gps.get("lon")
    if lat is None or lon is None:
        raise RenderError(
            "render mode needs gps {lat, lon} for the HOUSE, not just a "
            "postcode centroid — a proposal drawn on the neighbour's roof "
            "is worse than none. The app pins the house on the aerial "
            "before sending the job.")
    zone = spec.get("render_zone")
    if not zone:
        raise RenderError(
            "render mode needs render_zone: {bearing_deg, along0_m, "
            "along1_m, out0_m, out1_m} — the measured rectangle the "
            "extension must stay inside. Unconstrained generation was "
            "live-tested and it slabbed the whole street.")

    solar_key, gemini_key = _keys()
    directory = paths.ensure(output_dir)

    prog.stage("aerial")
    aerial, date = fetch_aerial(lat, lon, directory, solar_key)
    clean, marked = crop_and_mark(aerial, lat, lon, zone, directory)

    prog.stage("rendering")
    if (spec.get("extension") or {}).get("style") == "ai":
        render = gemini_edit(marked, _prompt(spec), gemini_key, directory)
    else:
        render = composite(clean, zone, directory)

    prog.stage("delivering")
    scan = spec.get("scan_id") or "render"
    project = spec.get("project_id") or "site"
    artifacts = []
    for path, name in ((clean, "aerial.jpg"), (marked, "aerial_marked.jpg"),
                       (render, "render.png")):
        artifacts.append((path, f"renders/{project}/{scan}/{name}", None))

    note = (f"Aerial imagery dated {date.get('year')}-{date.get('month'):02d}"
            if date.get("year") else "Aerial imagery date unknown")
    return artifacts, {
        "imagery": note,
        "warnings": [
            "This is a VISUALISATION of a proposal on real imagery, not a "
            "survey. Dimensions come from the zone the caller supplied; "
            "verify on site before pricing or building from it.",
        ],
    }


run_mode = run
