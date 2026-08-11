"""Capture quality and completeness — pure stdlib (pixel checks lazy-imported).

Two jobs, both taken directly from what the competitor apps do well:

  1. PER-IMAGE QUALITY TAGS. FairMoto tags each analysed photo — "good
     lighting", "reflection on panels", "water droplets", "indoor lighting",
     "minor shadow near wheel". These matter because they qualify the finding:
     a scratch called under glare is less certain than one in flat daylight,
     and a "water droplets" tag explains a false dent. The VLM emits these
     per image; this module normalises them and, when pixels are available,
     cross-checks the two cheap objective ones (too dark, too blurry) so the
     app can ask for a re-shot before the user has walked away.

  2. CAPTURE COMPLETENESS. DAMAGE iD's whole UI is a guided grid — Front,
     Pass-Front, Pass-Rear, Driver-Front, Dashboard - each a slot to fill.
     A one-photo inspection misses three-quarters of the car. This compares
     the panels actually seen against taxonomy.CAPTURE_GRID and tells the app
     exactly which angles are still needed, so the guidance is "add the rear
     and driver's side", not a silent partial result.

The objective pixel checks are deliberately minimal and lazy-imported: the CI
test runner has no numpy or PIL (by design), so the module must be fully
usable — tags, completeness, gating — with the VLM-provided tags alone.
"""
from taxonomy import CAPTURE_GRID, PANELS, canonical_panel

# Quality tags we recognise, grouped by whether they should BLOCK confident
# analysis (obscuring) or merely QUALIFY it (contextual). Synonyms map in.
BLOCKING_TAGS = {
    "too_dark", "underexposed", "overexposed", "blurry", "out_of_focus",
    "heavy_glare", "obstructed", "too_far", "motion_blur",
}
QUALIFYING_TAGS = {
    "reflection", "water_droplets", "dirt", "shadow", "indoor_lighting",
    "low_light", "wet", "snow", "harsh_sunlight", "backlit",
}

_TAG_SYNONYMS = {
    "dark": "too_dark", "low light": "low_light", "dim": "low_light",
    "underexposed": "underexposed", "overexposed": "overexposed",
    "blur": "blurry", "blurry": "blurry", "out of focus": "out_of_focus",
    "glare": "heavy_glare", "reflections": "reflection",
    "reflection on panels": "reflection", "water droplets": "water_droplets",
    "wet": "wet", "raindrops": "water_droplets", "dirty": "dirt",
    "mud": "dirt", "dusty": "dirt", "shadows": "shadow",
    "indoor": "indoor_lighting", "indoor lighting": "indoor_lighting",
    "far": "too_far", "distant": "too_far", "obstructed": "obstructed",
    "occluded": "obstructed", "harsh sunlight": "harsh_sunlight",
    "good lighting": "good_lighting", "backlit": "backlit",
}


def normalize_tag(tag):
    if not tag:
        return None
    s = str(tag).strip().lower().replace("-", " ")
    s = " ".join(s.split())
    if s in _TAG_SYNONYMS:
        return _TAG_SYNONYMS[s]
    return s.replace(" ", "_")


def classify_tags(tags):
    """Split a raw tag list into (blocking, qualifying, other)."""
    blocking, qualifying, other = [], [], []
    for t in tags or []:
        n = normalize_tag(t)
        if not n or n == "good_lighting":
            continue
        if n in BLOCKING_TAGS:
            blocking.append(n)
        elif n in QUALIFYING_TAGS:
            qualifying.append(n)
        else:
            other.append(n)
    return blocking, qualifying, other


def image_quality(image_meta):
    """Normalise one image's quality report.

    image_meta: {"tags": [...], "panels": [...], optional "local_path"/"url"}.
    Returns a normalised record with a usable flag and, if pixels are
    reachable, objective brightness/sharpness. The VLM tags are authoritative;
    pixels only ADD blocking tags they missed, never remove one.
    """
    tags = list(image_meta.get("tags") or [])
    blocking, qualifying, other = classify_tags(tags)

    objective = _pixel_checks(image_meta)
    for t in objective.get("add_blocking", []):
        if t not in blocking:
            blocking.append(t)

    return {
        "ref": image_meta.get("url") or image_meta.get("local_path")
               or image_meta.get("id"),
        "panels": [canonical_panel(p) or p for p in
                   (image_meta.get("panels") or [])],
        "blocking_tags": blocking,
        "qualifying_tags": qualifying,
        "other_tags": other,
        "usable": not blocking,
        "objective": objective.get("metrics"),
    }


def _pixel_checks(image_meta):
    """Cheap objective checks IF numpy+PIL and a local file are available.

    Returns {"add_blocking": [...], "metrics": {...}} or empty. Never raises
    and never imports at module load — the test runner has neither library.
    """
    path = image_meta.get("local_path")
    if not path:
        return {}
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return {}
    try:
        im = Image.open(path).convert("L")
        arr = np.asarray(im, dtype="float32")
    except Exception:
        return {}
    add = []
    mean = float(arr.mean())
    # Laplacian variance is the standard cheap sharpness proxy.
    lap = (arr[1:-1, 1:-1] * 4 - arr[:-2, 1:-1] - arr[2:, 1:-1]
           - arr[1:-1, :-2] - arr[1:-1, 2:])
    sharp = float(lap.var())
    if mean < 45:
        add.append("too_dark")
    if mean > 235:
        add.append("overexposed")
    if sharp < 60:
        add.append("blurry")
    return {"add_blocking": add,
            "metrics": {"brightness": round(mean, 1),
                        "sharpness": round(sharp, 1)}}


def seen_panels(findings, images):
    """Every taxonomy panel id that appears in the findings or the per-image
    panel lists — i.e. what the capture actually covered."""
    seen = set()
    for f in findings or []:
        p = canonical_panel(f.get("panel"))
        if p:
            seen.add(p)
    for im in images or []:
        for p in im.get("panels") or []:
            cp = canonical_panel(p)
            if cp:
                seen.add(cp)
    return seen


def completeness(findings, images):
    """Which regions of the capture grid are covered, and what's missing.

    Returns a per-region coverage report plus a flat list of the highest-value
    missing angles, so the app can prompt "add the rear and the driver's side"
    the way DAMAGE iD's grid does — before the car is gone.
    """
    seen = seen_panels(findings, images)
    regions = {}
    missing_regions = []
    for region, panels in CAPTURE_GRID.items():
        covered = [p for p in panels if p in seen]
        missing = [p for p in panels if p not in seen]
        frac = len(covered) / float(len(panels)) if panels else 1.0
        regions[region] = {
            "covered": covered,
            "missing": missing,
            "coverage": round(frac, 2),
        }
        if frac < 0.5:
            missing_regions.append(region)

    all_panels = {p for ps in CAPTURE_GRID.values() for p in ps}
    overall = len(seen & all_panels) / float(len(all_panels))
    guidance = []
    for region in ("front", "left", "right", "rear", "roof", "wheels"):
        r = regions.get(region)
        if r and r["coverage"] < 0.5:
            labels = ", ".join(PANELS[p][0] for p in r["missing"][:3])
            guidance.append(f"Add {region} views ({labels})")

    return {
        "overall_coverage": round(overall, 2),
        "regions": regions,
        "missing_regions": missing_regions,
        "guidance": guidance,
        "complete": overall >= 0.75 and not missing_regions,
    }


def overall_quality(images):
    """One capture-quality verdict across all images for the report header."""
    reports = [image_quality(im) for im in images or []]
    usable = [r for r in reports if r["usable"]]
    blocking = sorted({t for r in reports for t in r["blocking_tags"]})
    qualifying = sorted({t for r in reports for t in r["qualifying_tags"]})
    n = len(reports)
    return {
        "images": reports,
        "image_count": n,
        "usable_count": len(usable),
        "blocking_tags": blocking,
        "qualifying_tags": qualifying,
        # if fewer than half the images are usable, the whole result is shaky
        "reliable": (n == 0) or (len(usable) >= max(1, n // 2)),
    }
