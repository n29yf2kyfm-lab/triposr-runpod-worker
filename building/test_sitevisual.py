"""Tests for Render Mode — a proposal drawn onto real imagery.

Network-free: geometry, validation and the failure contract. The Gemini and
Solar calls are exercised live by the deployed worker, not here.

Run: python building/test_sitevisual.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sitevisual as S  # noqa: E402
import validation       # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. the constraint rectangle ---------------------------------------------
zone = {"bearing_deg": 312.0, "along0_m": -2.2, "along1_m": 2.2,
        "out0_m": 6.3, "out1_m": 11.0, "out_positive": True}
poly = S.zone_polygon(zone)
check("1a four corners", len(poly) == 4)
d01 = math.dist(poly[0], poly[1]); d12 = math.dist(poly[1], poly[2])
check("1b along edge is 4.4m at 25px/m", abs(d01 - 4.4 * 25) < 1.0, str(d01))
check("1c out edge is 4.7m at 25px/m", abs(d12 - 4.7 * 25) < 1.0, str(d12))
# perpendicularity — a sheared rectangle would put the proposal askew
v1 = (poly[1][0]-poly[0][0], poly[1][1]-poly[0][1])
v2 = (poly[2][0]-poly[1][0], poly[2][1]-poly[1][1])
dot = v1[0]*v2[0] + v1[1]*v2[1]
check("1d edges perpendicular", abs(dot) < 1e-6, str(dot))
# bearing 0 = north: along runs vertically in image (y), out to the east
p0 = S.zone_polygon({"bearing_deg": 0.0, "along0_m": 0, "along1_m": 4,
                     "out0_m": 0, "out1_m": 3})
check("1e north bearing runs up the image",
      abs(p0[0][0]-p0[1][0]) < 1e-6 and p0[1][1] < p0[0][1])
check("1f out_positive false mirrors the zone",
      S.zone_polygon(dict(zone, out_positive=False))[2][0] != poly[2][0])

# --- 2. validation: the joint ------------------------------------------------
s = validation.parse_job({"mode": "render", "gps": {"lat": 52.47, "lon": -2.07},
                          "render_zone": {"bearing_deg": 312, "along0_m": -2.2,
                                          "along1_m": 2.2, "out0_m": 6.3,
                                          "out1_m": 11.0}})
check("2a a full render job parses", s["render_zone"]["bearing_deg"] == 312.0)

for bad, why in [
    ({"mode": "render", "gps": {"lat": 52.47, "lon": -2.07}}, "no zone"),
    ({"mode": "render",
      "render_zone": {"bearing_deg": 1, "along0_m": 0, "along1_m": 1,
                      "out0_m": 0, "out1_m": 1}}, "no gps"),
    ({"mode": "render", "gps": {"lat": 52.47, "lon": -2.07},
      "render_zone": {"bearing_deg": 1, "along0_m": 2, "along1_m": 1,
                      "out0_m": 0, "out1_m": 1}}, "along reversed"),
    ({"mode": "render", "gps": {"lat": 52.47, "lon": -2.07},
      "render_zone": {"bearing_deg": 1, "along0_m": 0, "along1_m": 25,
                      "out0_m": 0, "out1_m": 1}}, "25m span"),
    ({"mode": "render", "gps": {"lat": 52.47, "lon": -2.07},
      "render_zone": {"bearing_deg": 1, "along0_m": 0,
                      "out0_m": 0, "out1_m": 1}}, "missing edge"),
]:
    try:
        validation.parse_job(bad)
        check(f"2b refused: {why}", False)
    except validation.InputError:
        check(f"2b refused: {why}", True)

# --- 3. failure contract -----------------------------------------------------
_env = dict(os.environ)
os.environ.pop("GOOGLE_SOLAR_API_KEY", None)
os.environ.pop("GOOGLE_AI_API_KEY", None)
try:
    S._keys()
    check("3a missing keys refuse loudly", False)
except S.RenderError as e:
    check("3a missing keys refuse loudly", "GOOGLE_SOLAR_API_KEY" in str(e))
os.environ["GOOGLE_SOLAR_API_KEY"] = "x"
try:
    S._keys()
    check("3b missing Gemini key names itself", False)
except S.RenderError as e:
    check("3b missing Gemini key names itself", "GOOGLE_AI_API_KEY" in str(e))
os.environ.clear(); os.environ.update(_env)

# --- 4. the prompt keeps its constraint teeth --------------------------------
p = S._prompt({"extension": {"finish": "buff brick", "roof": "flat roof",
                             "features": "bifold doors"}})
check("4a constraint wording present", "EXACTLY AND ONLY WITHIN" in p)
check("4b caller's finish carried", "buff brick" in p)
check("4c outline removal instructed", "REMOVE the red outline" in p)
p2 = S._prompt({})
check("4d defaults exist when caller silent", "brickwork" in p2)


# --- 5. the deterministic composite stays inside its zone -------------------
# Two live endpoint runs proved the AI cannot be trusted with geometry; the
# composite exists so the roof CANNOT land on the street. Verified by
# construction: every changed pixel lies within the zone's bounding box
# plus the shadow margin.
import tempfile
from PIL import Image
import numpy as np

with tempfile.TemporaryDirectory() as td:
    base = os.path.join(td, "aerial_crop.jpg")
    Image.new("RGB", (900, 900), (120, 110, 100)).save(base, quality=92)
    out = S.composite(base, zone, td)
    a = np.asarray(Image.open(base).convert("RGB"), dtype=int)
    b = np.asarray(Image.open(out).convert("RGB"), dtype=int)
    diff = (np.abs(a - b).sum(axis=2) > 12)
    ys, xs = np.nonzero(diff)
    check("5a the composite changed something", len(xs) > 1000)
    pol = S.zone_polygon(zone)
    pxs = [p[0] for p in pol]; pys = [p[1] for p in pol]
    m = 30   # shadow + fascia margin
    inside = ((xs >= min(pxs) - m) & (xs <= max(pxs) + m) &
              (ys >= min(pys) - m) & (ys <= max(pys) + m))
    check("5b every changed pixel is inside the zone (+shadow margin)",
          bool(inside.all()),
          f"{int((~inside).sum())} stray pixels")
    check("5c rooflights present (bright frames on dark roof)",
          bool((b[diff][:, 0] > 180).any()))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
