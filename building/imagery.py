"""Read the front of the house off the photo the pipeline already had.

The flagship mode's worst caveat was "window and door positions are placed
by rule — not surveyed", defended in its docstring with "nothing open gives
where the openings are". An audit pointed out the contradiction sitting in
the same scratchpad: the pipeline downloads Street View PHOTOS of the actual
elevation and then uses only the camera's coordinates, throwing away the
pixels that show every window, the door, the bay and the chimney. This
module reads them.

HOW MUCH TO TRUST IT. A photo reading is a MEASUREMENT OF THE PICTURE, not
of the wall: positions come back as fractions of the facade and land within
a couple of hundred millimetres at best, and the vision model can miss an
opening behind a hedge or invent one in deep shadow. That is still a
different universe from a rule that puts one window per wall at its centre —
but it is delivered as "read from imagery (positions approximate)", never as
"measured", and the on-site check list says to verify before ordering.

ATTRIBUTION. Street View Static API imagery carries Google's attribution
burned into the frame, and Google's terms require it stays visible. Nothing
here crops, inpaints or removes it, and the photo lands in the artifacts
with its attribution exactly as served.
"""
import base64
import json
import os
import re
import sys

import model3d


GEMINI_READ_MODEL = "gemini-flash-latest"
GEMINI_READ_API = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{GEMINI_READ_MODEL}:generateContent")
STREETVIEW_IMG = "https://maps.googleapis.com/maps/api/streetview"

# An opening narrower than this fraction of the facade is noise — a vent, a
# meter box, a misread. One wider than this is the model hallucinating a
# curtain wall onto a semi.
MIN_FRAC = 0.03
MAX_FRAC = 0.60


def _requests():
    import requests
    return requests


def fetch_photo(lat, lon, heading, key, path, fov=70, size="640x640"):
    """One Street View frame of the elevation, attribution intact."""
    r = _requests().get(STREETVIEW_IMG, params={
        "size": size, "location": f"{lat},{lon}", "heading": round(heading, 1),
        "pitch": 5, "fov": fov, "source": "outdoor", "key": key}, timeout=90)
    r.raise_for_status()
    if len(r.content) < 5000:
        return None          # the grey "no imagery" tile
    with open(path, "wb") as f:
        f.write(r.content)
    return path


_PROMPT = (
    "You are reading the FRONT ELEVATION of the main house in this "
    "photograph for an architectural survey. Answer with ONLY a JSON "
    "object, no prose, no markdown fences.\n\n"
    "Schema:\n"
    "{\n"
    '  "storeys": <int, visible storeys of the main house>,\n'
    '  "finish": "brick" | "render" | "pebbledash" | "stone" | "mixed",\n'
    '  "chimney": <bool>,\n'
    '  "openings": [\n'
    '    {"floor": <0 ground | 1 first>, "kind": "door"|"window"|"bay",\n'
    '     "x0": <float 0-1, left edge as fraction of the facade width>,\n'
    '     "x1": <float 0-1, right edge>}\n'
    "  ]\n"
    "}\n\n"
    "Rules: fractions run left to right across the MAIN house's facade only "
    "— exclude any attached neighbour. A bay window is kind \"bay\" once, "
    "not its individual panes. If you cannot see the facade clearly, return "
    '{"unreadable": true}.'
)


def read_facade(photo_path, gemini_key):
    """The facade as structured data, or None with the reason on stderr."""
    try:
        with open(photo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        body = {"contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            {"text": _PROMPT}]}]}
        r = _requests().post(GEMINI_READ_API, params={"key": gemini_key},
                             json=body, timeout=120)
        if r.status_code != 200:
            print(f"facade read: HTTP {r.status_code} {r.text[:120]}",
                  file=sys.stderr)
            return None
        parts = (((r.json().get("candidates") or [{}])[0]
                  .get("content") or {}).get("parts") or [])
        text = " ".join(p.get("text", "") for p in parts)
        return parse_reading(text)
    except Exception as e:
        print(f"facade read failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def parse_reading(text):
    """Pull the JSON out of a model reply that may wrap it in noise."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("unreadable"):
        return None
    ops = []
    for o in data.get("openings") or []:
        try:
            x0, x1 = float(o["x0"]), float(o["x1"])
            floor = int(o.get("floor", 0))
            kind = str(o.get("kind", "window"))
        except (KeyError, TypeError, ValueError):
            continue
        if x1 <= x0 or not (0.0 <= x0 < 1.0) or not (0.0 < x1 <= 1.0):
            continue
        if not MIN_FRAC <= (x1 - x0) <= MAX_FRAC:
            continue
        if kind not in ("door", "window", "bay"):
            continue
        if kind == "door" and floor != 0:
            continue           # a first-floor front door is a misread
        ops.append({"floor": max(0, min(floor, 2)), "kind": kind,
                    "x0": round(x0, 3), "x1": round(x1, 3)})
    if not ops:
        return None
    return {"storeys": max(1, min(int(data.get("storeys") or 2), 3)),
            "finish": data.get("finish"),
            "chimney": bool(data.get("chimney")),
            "openings": ops}


def to_wall_openings(reading, facade_width):
    """Photo fractions to model3d opening dicts on the front wall.

    The local frame puts the front elevation on y=0 with +x running along
    it; a camera on the street looks at that face with +x to its right, so
    the photo's left-to-right IS the wall's along-axis. Bays are returned
    separately — they are geometry, not holes in a wall.
    """
    openings, bays = [], []
    for o in reading["openings"]:
        along = o["x0"] * facade_width
        w = (o["x1"] - o["x0"]) * facade_width
        if o["kind"] == "bay":
            # A bay reported on both floors is ONE two-storey bay, not two
            # stacked bays — the 1930s semi's signature front. Merge on
            # overlap and keep how many storeys the photo showed.
            for b in bays:
                if along < b["x"] + b["width"] and b["x"] < along + w:
                    # Both edges are read BEFORE either is written. Taking
                    # the right edge from b["x"] after b["x"] had already
                    # moved left lost the difference off the merged bay, so
                    # a bay whose upper storey reads further left came out
                    # narrower than the photo showed.
                    left = min(b["x"], along)
                    right = max(b["x"] + b["width"], along + w)
                    b["x"] = round(left, 2)
                    b["width"] = round(right - left, 2)
                    b["storeys"] = max(b["storeys"], o["floor"] + 1)
                    break
            else:
                bays.append({"x": round(along, 2), "width": round(w, 2),
                             "storeys": o["floor"] + 1})
            continue
        if o["kind"] == "door":
            openings.append({"kind": "door", "along": round(along, 2),
                             "width": round(min(w, 1.2), 2),
                             "height": model3d.DOOR_H_M, "sill": 0.0,
                             "level": 0})
        else:
            openings.append({"kind": "window", "along": round(along, 2),
                             "width": round(w, 2),
                             "height": model3d.WINDOW_H_M,
                             "sill": model3d.WINDOW_SILL_M,
                             "level": o["floor"]})
    return openings, bays
