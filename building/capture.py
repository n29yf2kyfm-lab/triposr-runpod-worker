"""The shot list — what the homeowner actually has to film, for THIS house.

Everything downstream of here needs a capture, and "walk round the house
filming it" is the instruction that has produced nothing usable so far. A
reconstruction fails for reasons a person cannot see while holding the phone:
too close for the roof to fit the frame, too few frames between corners, pure
rotation instead of walking, one elevation missed because there was a fence
in the way.

So the plan is COMPUTED from the building already measured — its footprint,
its ridge height, and, crucially, the clearances probed against the
neighbours. That last one is what a generic instruction can never give:
where a semi is attached there is no ground to stand on, and telling someone
to photograph a wall they cannot reach is how a capture session ends in a
shrug. This says which elevations are reachable, where to stand for each,
how far apart the shots go, and which ones are impossible and why.

WHAT IT IS SIZED FOR. Two different jobs, from one walk:

  measured mesh   needs parallax and coverage — walk between shots, overlap
                  them heavily, and get every corner from both sides
  Gaussian splat  needs the same, plus MORE of it: dense views all the way
                  round, even exposure, nothing moving in the scene

Both are served by one dense orbit, which is why this produces a ring rather
than "four photos of four walls". The frame spacing comes from the iPhone's
actual field of view at the computed standoff, not from a round number.
"""
import math


# iPhone main (wide) camera, 26mm equivalent on a 36x24mm frame. Held in
# PORTRAIT, which is what fits a house: the long side of the sensor runs
# vertically, so the 69 degrees is the one that has to swallow the ridge.
FOV_TALL_DEG = 69.4
FOV_WIDE_DEG = 49.9

# Phone held at chest height by someone walking. Not eye height — people
# lower the phone to see the screen.
EYE_HEIGHT_M = 1.5

# Overlap between neighbouring frames. Photogrammetry convention is 60-80%;
# splats want the top of that range because every gaussian needs to be seen
# from several angles before its shape is constrained.
OVERLAP = 0.75

# Headroom so the ridge is not clipped by the frame edge, where lens
# distortion is worst and the matcher is least reliable.
FRAME_MARGIN = 1.18

# A ring closer than this to the wall cannot see the roof on a two-storey
# house whatever the maths says, and the phone starts focusing on brick.
MIN_STANDOFF_M = 3.0

# Below this there is no standing room at all — a party wall, or a gap too
# narrow to walk with a phone held out. Anything above it is shootable, just
# not from as far back as one would like.
NO_ACCESS_M = 1.2

# THE WHOLE ELEVATION DOES NOT HAVE TO FIT ONE FRAME.
#
# The first version of this computed the distance that fits the ridge in a
# single portrait shot — 11.1m for an 8m ridge — and then refused both sides
# of a semi with 2.75m and 0m of clearance. That is the wrong answer for the
# wrong reason: photogrammetry and splatting want DENSE overlapping coverage,
# not one framing of the whole wall. Where the plot is tight you stand closer
# and shoot in horizontal tiers, tilting up, with more frames. The full-height
# standoff stays useful for one reference shot per elevation and for nothing
# else. Three tiers is the practical ceiling before a handheld pass stops
# being repeatable.
MAX_TIERS = 3

# Apple's LiDAR is confident to about five metres. Beyond that the depth is
# extrapolated and the scale it contributes is worth less than the
# photogrammetry it was meant to anchor.
LIDAR_RANGE_M = 5.0

# Metres per degree of latitude. Longitude narrows with the cosine of it.
M_PER_DEG_LAT = 111320.0


def standoff(height_m, fov_deg=FOV_TALL_DEG, eye_h=EYE_HEIGHT_M):
    """How far back to stand so the whole elevation fits the frame.

    The camera is not on the ground, so the angle it must cover is the ridge
    ABOVE the phone plus the ground below it — the taller half sets the
    distance. Getting this wrong is the single commonest capture failure:
    stand where it feels natural, and the roof is out of frame in every shot
    of a two-storey house.
    """
    half = math.tan(math.radians(fov_deg) / 2.0)
    if half <= 0:
        raise ValueError("a camera with no field of view cannot see a house")
    need = max(height_m - eye_h, eye_h)
    return max(MIN_STANDOFF_M, round(need / half * FRAME_MARGIN, 1))


def frame_step(distance_m, fov_deg=FOV_WIDE_DEG, overlap=OVERLAP):
    """How far to walk between shots to hold the overlap.

    Coverage across the frame at that distance, times the fraction that must
    be NEW in the next one. Walking further loses the match; walking less
    wastes frames and battery.
    """
    across = 2.0 * distance_m * math.tan(math.radians(fov_deg) / 2.0)
    return max(0.4, round(across * (1.0 - overlap), 2))


def side_runs(width, depth, gaps):
    """One walking line per elevation, each at its OWN standoff.

    A single offset rectangle assumes every side has the same room, which is
    exactly what a real plot does not have. Returning the four runs
    separately lets a 12m rear be walked from 11m back while a 2.75m side
    alley is walked from 2.4m, in the same session.
    """
    runs = []
    g = gaps.get("front", 3.0)
    runs.append(("front", (-g * 0.55, -g), (width + g * 0.55, -g)))
    g = gaps.get("east", 3.0)
    runs.append(("east", (width + g, -g * 0.55), (width + g, depth + g * 0.55)))
    g = gaps.get("rear", 3.0)
    runs.append(("rear", (width + g * 0.55, depth + g),
                 (-g * 0.55, depth + g)))
    g = gaps.get("west", 3.0)
    runs.append(("west", (-g, depth + g * 0.55), (-g, -g * 0.55)))
    return runs


# Which measured clearance governs standing off each elevation.
_CLEAR_FOR = {"front": "south", "rear": "north", "east": "east",
              "west": "west"}


def to_latlon(local, angle, origin_en, lat0, lon0, origin_latlon_en):
    """Local plan metres to WGS84, on the local tangent plane.

    Over the twenty metres someone walks round a house this is accurate to
    centimetres, and it avoids inverting the OSGB projection for a figure
    whose job is to drop a pin on a map. The eastings and northings are OS
    grid, so a heading taken from them is a GRID bearing — within about a
    degree of true in the Midlands, and a phone compass shows magnetic
    anyway, so the written instruction leads and the bearing supports it.
    """
    c, s = math.cos(angle), math.sin(angle)
    e = local[0] * c - local[1] * s + origin_en[0]
    n = local[0] * s + local[1] * c + origin_en[1]
    de, dn = e - origin_latlon_en[0], n - origin_latlon_en[1]
    lat = lat0 + dn / M_PER_DEG_LAT
    lon = lon0 + de / (M_PER_DEG_LAT * max(
        math.cos(math.radians(lat0)), 1e-6))
    return round(lat, 7), round(lon, 7)


def bearing_to(frm, to):
    """Grid bearing from one local point to another, degrees from north.

    The local frame has +y running INTO the plot from the front, so local
    north is the frame's +y and a bearing is measured clockwise from it.
    """
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    return round(math.degrees(math.atan2(dx, dy)) % 360.0, 1)


def plan(model, lat, lon):
    """The whole capture, as a numbered list of things to do.

    `model` is a Propose Mode result — it carries the plan dimensions, the
    ridge height and the measured clearances this is built from.
    """
    site = model.get("site") or {}
    plan_m = site.get("plan_m") or {}
    width = float(plan_m.get("width") or 0)
    depth = float(plan_m.get("depth") or 0)
    if width <= 0 or depth <= 0:
        raise ValueError("no measured plan to build a capture around")

    roof = model.get("roof") or {}
    ridge = float(roof.get("ridge_z_m") or model.get("eaves_z_m") or 5.5)
    clear = site.get("clearances_m") or {}
    frame = site.get("frame") or {}
    angle = float(frame.get("angle_rad") or 0.0)
    origin = frame.get("origin_en") or [0.0, 0.0]
    anchor = frame.get("anchor_en") or origin

    ideal = standoff(ridge)

    # Per elevation: how far back can you ACTUALLY get, and how many tiers
    # does that force.
    gaps, tiers, blocked = {}, {}, []
    for side, key in _CLEAR_FOR.items():
        have = clear.get(key)
        have = ideal if have is None else float(have)
        if have < NO_ACCESS_M:
            blocked.append({
                "side": side, "measured_clear_m": round(have, 2),
                "why": ("This is the party wall of an attached house — there "
                        "is no ground to stand on. It will be reconstructed "
                        "from the corners only, and the model should not be "
                        "trusted along it."
                        if have <= 0.2 else
                        f"Only {have:.2f}m of clear ground was measured here "
                        f"— too narrow to walk with the phone held out. "
                        f"Shoot the corners and accept a weak elevation.")})
            continue
        use = max(MIN_STANDOFF_M * 0.55, min(ideal, have - 0.3))
        gaps[side] = round(use, 2)
        # Vertical coverage at that distance, against the height to cover.
        covers = 2.0 * use * math.tan(math.radians(FOV_TALL_DEG) / 2.0)
        tiers[side] = max(1, min(MAX_TIERS,
                                 int(math.ceil(ridge / max(covers, 0.1)))))

    if not gaps:
        raise ValueError(
            "every elevation is blocked — there is nowhere to stand and no "
            "capture to plan")

    runs = [r for r in side_runs(width, depth, gaps) if r[0] in gaps]
    shots, n = [], 0
    for side, p, q in runs:
        use = gaps[side]
        step = frame_step(use)
        run = math.hypot(q[0] - p[0], q[1] - p[1])
        count = max(2, int(math.ceil(run / step)) + 1)
        for tier in range(tiers[side]):
            for k in range(count):
                t = k / float(count - 1)
                here = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
                aim = (min(max(here[0], 0.0), width),
                       min(max(here[1], 0.0), depth))
                n += 1
                ll = to_latlon(here, angle, origin, lat, lon, anchor)
                shots.append({
                    "no": n, "side": side, "tier": tier + 1,
                    "gps": {"lat": ll[0], "lon": ll[1]},
                    "heading_deg": bearing_to(here, aim),
                    "standoff_m": use,
                    "tilt": ("level" if tiers[side] == 1 else
                             ["level", "up 25 degrees", "up 45 degrees"]
                             [min(tier, 2)]),
                })

    sides = sorted(gaps)
    tight = [k for k in sides if tiers[k] > 1]
    passes = [
        {"name": "main orbit", "height_m": EYE_HEIGHT_M,
         "frames": len(shots), "hold": "portrait",
         "note": ("Walk it. WALK between shots — do not stand in one place "
                  "and turn. A turn gives the matcher no parallax and the "
                  "reconstruction collapses into a smear.")},
        {"name": "raised pass", "height_m": 2.2,
         "frames": max(12, len(shots) // 3), "hold": "portrait",
         "note": ("Same route, phone held high and tilted down onto the "
                  "roof. This is the only pass that sees the roof slopes "
                  "and the tops of the walls.")},
        {"name": "LiDAR close pass", "height_m": EYE_HEIGHT_M,
         "frames": max(16, len(shots) // 2), "hold": "portrait",
         "note": (f"Slow walk within {LIDAR_RANGE_M:.0f}m of the wall. "
                  f"Past that the depth sensor is extrapolating, and its "
                  f"whole job here is to put a true scale on the model.")},
    ]

    return {
        "for": site.get("address"),
        "ridge_height_m": round(ridge, 2),
        "full_height_standoff_m": ideal,
        "standoff_m": {k: gaps[k] for k in sides},
        "tiers": {k: tiers[k] for k in sides},
        "frame_step_m": {k: frame_step(gaps[k]) for k in sides},
        "field_of_view": {"tall_deg": FOV_TALL_DEG, "wide_deg": FOV_WIDE_DEG,
                          "held": "portrait"},
        "passes": passes,
        "shots": shots,
        "total_frames": sum(r["frames"] for r in passes),
        "tight_sides": tight,
        "blocked": blocked,
        "also": [
            "At each reachable corner take one shot along BOTH elevations "
            "that meet there. Corners are where a reconstruction splits into "
            "two halves that never line up.",
            "Shoot the rear elevation square-on as well as from the walk — "
            "that is the wall the extension lands on.",
            "One close, straight-on shot of every existing window and door. "
            "Until a photograph says otherwise the model places them by rule.",
        ],
        "conditions": [
            "Bright overcast is the best weather for this. Hard sun bakes "
            "shadows into the model that cannot be relit afterwards.",
            "One continuous session. Move a car, open a curtain or let the "
            "light swing round between passes and those frames stop matching "
            "the rest.",
            "Nothing moving in shot — nobody walking through, no washing on "
            "the line, no bins out.",
            "Do not zoom and do not switch lenses mid-pass. A change of "
            "focal length reads to the matcher as a different camera.",
        ]
        + ([f"The {', '.join(tight)} elevation(s) are tight, so they are "
            f"shot in tiers: walk each one more than once, tilting further "
            f"up each time. The whole wall will not fit one frame and does "
            f"not need to."] if tight else []),
        "warning": (
            "This plan is built from the measured outline and the clearances "
            "probed against neighbouring buildings. It cannot see fences, "
            "hedges, sheds or parked cars. Where the ground is not walkable, "
            "get what you can from the corners and record which frames are "
            "missing rather than guessing them."),
    }
