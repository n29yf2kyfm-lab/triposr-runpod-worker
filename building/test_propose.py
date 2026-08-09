"""Tests for Propose Mode — an address in, a designed extension out.

Network-free: the plan geometry, the fit rules and the refusal contract. The
OSM, Solar and Street View calls are exercised live against real addresses,
not here — what is tested here is everything that decides where the walls go
once the data has arrived.

Run: python building/test_propose.py
"""
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# handler imports the RunPod SDK, which is not installed for tests. The same
# stub test_handler.py uses, so importing it here checks the wiring rather
# than the presence of a deployment dependency.
_runpod = types.ModuleType("runpod")
_serverless = types.ModuleType("runpod.serverless")
_serverless.progress_update = lambda *a, **k: None
_runpod.serverless = _serverless
sys.modules.setdefault("runpod", _runpod)
sys.modules.setdefault("runpod.serverless", _serverless)

import propose as P    # noqa: E402
import validation      # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. the minimum-area rectangle ------------------------------------------
# A 10 x 6 rectangle turned 30 degrees must come back 10 x 6 at 30 degrees,
# not as its 13.2 x 10.2 axis-aligned bounding box.
ang = math.radians(30)
base = [(0, 0), (10, 0), (10, 6), (0, 6)]
turned = [(x * math.cos(ang) - y * math.sin(ang) + 400,
           x * math.sin(ang) + y * math.cos(ang) + 300) for x, y in base]
r = P.min_area_rect(turned)
long_side, short_side = max(r["width_m"], r["depth_m"]), min(r["width_m"],
                                                             r["depth_m"])
check("1a recovers the true length", abs(long_side - 10) < 0.05,
      str(long_side))
check("1b recovers the true width", abs(short_side - 6) < 0.05,
      str(short_side))
check("1c area is the rectangle's, not the bounding box's",
      abs(r["area_m2"] - 60) < 0.5, str(r["area_m2"]))
check("1d centre is right", math.dist(r["centre"], (
    400 + 5 * math.cos(ang) - 3 * math.sin(ang),
    300 + 5 * math.sin(ang) + 3 * math.cos(ang))) < 0.05)
# The axis must be one of the rectangle's own edge directions — the outline
# was turned 30 degrees, so the recovered axis is 30 (mod 90), not 0.
axis = math.degrees(r["angle_rad"]) % 90
check("1e axis matches the 30 degree rotation", abs(axis - 30.0) < 0.5,
      str(axis))

# A degenerate outline is refused rather than roofed.
try:
    P.min_area_rect([(0, 0), (1, 1), (2, 2)])
    check("1f collinear outline refused", False)
except P.ProposeError:
    check("1f collinear outline refused", True)


# --- 2. bearings -------------------------------------------------------------
# Easting is x, northing is y, so maths-east is bearing 90 and maths-north 0.
check("2a east is 090", abs(P.bearing_of(0.0) - 90.0) < 1e-6)
check("2b north is 000", abs(P.bearing_of(math.pi / 2) % 360) < 1e-6)
check("2c west is 270", abs(P.bearing_of(math.pi) - 270.0) < 1e-6)


# --- 3. which side the road is on -------------------------------------------
rect = {"angle_rad": 0.0, "width_m": 10.0, "depth_m": 6.0,
        "centre": (0.0, 0.0), "area_m2": 60.0}
check("3a camera to the south gives the south front",
      P.choose_front(rect, (0.0, -20.0)) == "south")
check("3b camera to the north gives the north front",
      P.choose_front(rect, (0.0, 20.0)) == "north")
check("3c camera to the east gives the east front",
      P.choose_front(rect, (20.0, 0.0)) == "east")
check("3d no camera means no answer", P.choose_front(rect, None) is None)
# The rectangle's own rotation has to be undone, or a turned house reports
# the wrong elevation as its front.
turned_rect = dict(rect, angle_rad=math.pi / 2)
check("3e a house turned 90 degrees still finds its front",
      P.choose_front(turned_rect, (20.0, 0.0)) == "south")


# --- 4. the local frame -----------------------------------------------------
# Whatever the front, the house must land in +x/+y with the front on y=0.
for front in P.SIDES:
    a, o, w, d = P.local_frame(rect, front)
    corners = [P.to_local(P.to_world((x, y), a, o), a, o)
               for x, y in ((0, 0), (w, 0), (w, d), (0, d))]
    ok = all(abs(c[0] - e[0]) < 1e-6 and abs(c[1] - e[1]) < 1e-6
             for c, e in zip(corners, ((0, 0), (w, 0), (w, d), (0, d))))
    check(f"4a round trip is exact ({front})", ok)
    # The centre of the rectangle must still be the centre of the house.
    mid = P.to_world((w / 2, d / 2), a, o)
    check(f"4b centre preserved ({front})", math.dist(mid, (0.0, 0.0)) < 1e-6,
          str(mid))
    check(f"4c plan area preserved ({front})", abs(w * d - 60.0) < 1e-6)

# Facing east must swap the plan dimensions — the frontage becomes the 6m side.
_, _, w_e, d_e = P.local_frame(rect, "east")
check("4d facing east swaps width and depth",
      abs(w_e - 6.0) < 1e-6 and abs(d_e - 10.0) < 1e-6, f"{w_e}x{d_e}")


# --- 5. decomposing an L-shaped outline -------------------------------------
# A main block 10 x 8 with a 4 x 4 outrigger off the back.
ell = [(0, 0), (10, 0), (10, 8), (6, 8), (6, 12), (2, 12), (2, 8), (0, 8)]
pieces = P.decompose(ell)
check("5a finds more than one block", len(pieces) >= 2, str(pieces))
covered = sum(p[2] * p[3] for p in pieces)
check("5b covers most of the 96m2 outline", covered >= 96 * 0.85,
      f"{covered}")
check("5c every block is inside the outline",
      all(P.decompose and x >= -0.01 and y >= -0.01 and x + w <= 10.01
          and y + d <= 12.01 for x, y, w, d in pieces), str(pieces))
check("5d no sliver blocks", all(min(w, d) >= P.DECOMP_MIN_SIDE_M
                                 for _, _, w, d in pieces), str(pieces))

# A plain rectangle should come back as ONE block, not a mosaic.
one = P.decompose([(0, 0), (10, 0), (10, 8), (0, 8)])
check("5e a rectangle stays one block", len(one) == 1, str(one))

# A slightly skewed outline must not leave a 1m-deep phantom room behind it —
# this is the real failure that DECOMP_MIN_SIDE_M exists to stop.
skew = [(0, 0), (13.2, 0.4), (13.0, 9.9), (0.2, 9.5)]
sk = P.decompose(skew)
check("5f skewed outline yields no slivers",
      all(min(w, d) >= P.DECOMP_MIN_SIDE_M for _, _, w, d in sk), str(sk))


# --- 6. clipping a terrace row to one bay -----------------------------------
row = [(0, 0), (54.5, 0), (54.5, 13.9), (0, 13.9)]
bay = P.clip_to_strip(row, 32.16, 37.36)
xs = [p[0] for p in bay]
check("6a bay is clipped to the strip",
      abs(min(xs) - 32.16) < 1e-6 and abs(max(xs) - 37.36) < 1e-6, str(bay))
import roof as roofmod  # noqa: E402
check("6b bay area is width x depth",
      abs(abs(roofmod.polygon_area(bay)) - 5.2 * 13.9) < 0.01,
      str(roofmod.polygon_area(bay)))
check("6c clipping outside the polygon gives nothing",
      P.clip_to_strip(row, 80.0, 90.0) == [])


# --- 7. the extension fits the measured clearance ---------------------------
# Asked for 3m down the side; only 2.75m measured clear. Must build 2.15m and
# say why, NOT fail and NOT quietly build 3m into the neighbour.
clear = {"east": 2.75, "west": 0.0, "north": 12.0, "south": 12.0}
rooms, fit = P.place_extension(13.17, 9.9,
                               {"type": "side", "width_m": 3.0}, clear)
check("7a one extension room", len(rooms) == 1)
check("7b width cut to the buildable figure",
      abs(rooms[0].width - 2.15) < 0.01, str(rooms[0].width))
check("7c the reduction is reported", "reduced" in fit, str(fit))
check("7d it went on the open side", fit["side"] == "east", str(fit))
check("7e it does not overrun the clearance",
      rooms[0].width + P.SIDE_WORKING_CLEARANCE_M <= clear["east"] + 1e-9)

# The blocked side must never be chosen, even when asked for by name.
_, fit_w = P.place_extension(13.17, 9.9,
                             {"type": "side", "side": "west", "width_m": 2.5},
                             clear)
check("7f a blocked side is swapped for the open one",
      fit_w["side"] == "east", str(fit_w))

# Both sides blocked: refuse, and name the alternative that does work.
try:
    P.place_extension(13.17, 9.9, {"type": "side", "width_m": 3.0},
                      {"east": 0.4, "west": 0.0, "north": 12.0, "south": 12.0})
    check("7g both sides blocked refuses", False)
except P.ProposeError as e:
    check("7g both sides blocked refuses", "rear" in str(e).lower(), str(e))

# A rear extension is trimmed to the measured rear clearance.
rooms_r, fit_r = P.place_extension(10.0, 8.0, {"type": "rear", "depth_m": 6.0},
                                   {"east": 3, "west": 3, "north": 3.5,
                                    "south": 12})
check("7h rear depth cut to the clearance",
      abs(rooms_r[0].depth - 3.5) < 0.01, str(rooms_r[0].depth))
check("7i rear reduction reported", "reduced" in fit_r)
check("7j rear extension sits behind the house",
      abs(rooms_r[0].y - 8.0) < 1e-6, str(rooms_r[0].y))

# A multi-storey extension is built at the HOUSE'S storey height, not the
# assumed one. Defaulted to 2.75m against a house measured at 3.016m, every
# extension level sat 0.27m short and the mismatch rendered as an open seam
# between storeys — invisible from the drone angle, obvious at eye level.
rooms_h, _ = P.place_extension(10.0, 8.0,
                               {"type": "rear", "storeys": 2, "depth_m": 4.0},
                               {"east": 12, "west": 12, "north": 12,
                                "south": 12}, storey_h=3.016)
check("7k a 2-storey extension inherits the measured storey height",
      abs(rooms_h[0].height - 3.016) < 1e-6, str(rooms_h[0].height))
rooms_1, _ = P.place_extension(10.0, 8.0, {"type": "rear", "depth_m": 4.0},
                               {"east": 12, "west": 12, "north": 12,
                                "south": 12}, storey_h=3.016)
check("7l a single-storey extension keeps its own ceiling",
      rooms_1[0].height != 3.016, str(rooms_1[0].height))

# Sizes outside what this designs are refused rather than clamped silently.
for bad in (0.4, 25.0):
    try:
        P.place_extension(10, 8, {"type": "rear", "depth_m": bad}, clear)
        check(f"7k {bad}m depth refused", False)
    except P.ProposeError:
        check(f"7k {bad}m depth refused", True)
try:
    P.place_extension(10, 8, {"type": "conservatory"}, clear)
    check("7l unknown type refused", False)
except P.ProposeError:
    check("7l unknown type refused", True)

# A wrap with no room down either side degrades to the rear half and says so.
_, fit_wrap = P.place_extension(10.0, 8.0, {"type": "wrap", "depth_m": 3.0},
                                {"east": 0.5, "west": 0.0, "north": 12.0,
                                 "south": 12.0})
check("7m wrap without a side becomes a rear extension",
      isinstance(fit_wrap.get("return"), str), str(fit_wrap.get("return")))


# --- 8. the roof read off Solar ---------------------------------------------
payload = {
    "solarPotential": {
        "roofSegmentStats": [
            {"pitchDegrees": 35.0, "azimuthDegrees": 41.7,
             "stats": {"areaMeters2": 28.7},
             "planeHeightAtCenterMeters": 110.4},
            {"pitchDegrees": 35.0, "azimuthDegrees": 222.0,
             "stats": {"areaMeters2": 22.8},
             "planeHeightAtCenterMeters": 110.6},
            {"pitchDegrees": 9.0, "azimuthDegrees": 336.7,
             "stats": {"areaMeters2": 10.2},
             "planeHeightAtCenterMeters": 107.3},
        ],
        "buildingStats": {"groundAreaMeters2": 93.2, "areaMeters2": 110.0},
        "wholeRoofStats": {"groundAreaMeters2": 93.2, "areaMeters2": 110.0},
    },
    "imageryDate": {"year": 2022, "month": 5, "day": 14},
}
info = P.roof_from_solar(payload, span_m=9.9)
check("8a pitch is the measured one", abs(info["pitch_deg"] - 35.0) < 0.6,
      str(info["pitch_deg"]))
# Rise is half the span times tan(pitch) — 4.95 * tan(35) = 3.47m.
check("8b rise from span and pitch", abs(info["rise_m"] - 3.47) < 0.05,
      str(info["rise_m"]))
check("8c ridge runs across the slope",
      abs(info["ridge_bearing_deg"] - 131.7) < 0.1,
      str(info["ridge_bearing_deg"]))
check("8d highest plane kept", abs(info["plane_height_od_m"] - 110.6) < 0.01)
check("8e lowest plane kept", abs(info["lower_plane_od_m"] - 107.3) < 0.01)
check("8f solar footprint carried for cross-checking",
      abs(info["solar_footprint_m2"] - 93.2) < 0.01)
check("8g a roof with no pitched plane gives nothing",
      P.roof_from_solar({"solarPotential": {"roofSegmentStats": [
          {"pitchDegrees": 1.0, "azimuthDegrees": 0.0,
           "stats": {"areaMeters2": 30.0}}]}}, 9.9) is None)
check("8h an empty payload gives nothing", P.roof_from_solar({}, 9.9) is None)

# The 3.1m drop between the main roof and the lower one is a real reading of
# a second storey, and must be reported as measured rather than assumed.
n, src = P.storey_count(info)
check("8i two storeys", n == 2)
check("8j storeys called measured when the roofs differ", "measured" in src,
      src)
check("8k storeys called assumed with nothing to measure",
      P.storey_count(None)[1] == "assumed")


# --- 9. the validator's contract --------------------------------------------
check("9a propose is a known mode", "propose" in validation.MODES)
try:
    validation.parse_job({"mode": "propose"})
    check("9b propose with no location refused", False)
except validation.InputError as e:
    check("9b propose with no location refused", "address" in str(e), str(e))

spec = validation.parse_job({"mode": "propose", "address": "B36 8AR",
                             "extension": {"type": "rear", "depth_m": 4.0}})
check("9c address accepted", spec["address"] == "B36 8AR")
check("9d the brief survives validation",
      (spec["extension"] or {}).get("depth_m") == 4.0, str(spec["extension"]))

spec_g = validation.parse_job({"mode": "propose",
                               "gps": {"lat": 52.47, "lon": -2.06}})
check("9e gps alone is enough", spec_g["gps"]["lat"] == 52.47)

# The mode has to be wired into the worker, not merely written.
import handler  # noqa: E402
check("9f handler knows the module", handler._pipeline_available("propose"))
import progress  # noqa: E402
check("9g progress has a stage plan", len(progress.STAGE_PLANS["propose"]) > 0)
check("9h every stage run() emits is in the plan",
      set(["locating", "footprint", "orientation", "clearances", "roof",
           "designing", "exporting", "rendering", "photoreal"])
      == set(progress.STAGE_PLANS["propose"]))


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
