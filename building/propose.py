"""Propose Mode — an address in, a designed extension out, in measured 3D.

The pitch is one line: **type an address, get the house and its extension as a
model you can build from.** No scan, no drawing, no site visit.

WHY THIS IS NOT IMAGE-TO-3D. The obvious route is to photograph the house,
have an image model imagine the extension, and push the picture through
TRELLIS or Hunyuan3D to get a mesh. That produces something that looks
convincing from the camera angle and is mush behind it, at no particular
size. A builder cannot set out foundations from it, cannot price it, cannot
put it in front of building control. Single-image 3D generators are trained
on objects on turntables; a house is not that, and the mesh they return is
not dimensioned. This module goes the other way round — it takes REAL
measurements first and only then makes them look like the house:

    address
      -> postcodes.io                  lat / lon                    measured
      -> OpenStreetMap                 building outline             measured
      -> Google Solar buildingInsights roof pitch, azimuth, heights measured
      -> Street View metadata          which way the house faces    measured
      -> neighbouring outlines         which side is free to build  measured
      -> the brief                     how big the extension is     stated
      -> model3d                       walls, openings, roof        derived
      -> GLB / OBJ / IFC               1:1, in metres               output

Every dimension traces to one of those sources, and the delivered JSON says
which. Where a figure is a standard rather than a measurement — storey
height when there is no LIDAR to difference — it is labelled `assumed` and
counted in `confidence`, because the whole product rests on never presenting
a guess as a survey.

WHAT THE PHOTO ADDS, AND WHAT IT STILL CANNOT. Street View pixels are now
read for the FRONT elevation — windows, door, bays, finish, chimney — so the
front stops being placed by rule. The reading is a measurement of a
photograph, approximate to a couple of hundred millimetres, and the sides
and rear stay rule-placed until someone photographs them; the provenance
table says exactly which walls are which. A RoomPlan scan or a site capture
still beats all of it.
"""
import json
import math
import os
import sys

import model3d
import paths
import roof as roofmod
import solar


MODE = "propose"

# Street View's metadata endpoint is free and returns the pano's own
# position. That position is the camera, and the camera sits on the road —
# which is how this module knows which elevation is the front without anyone
# saying so.
STREETVIEW_META = "https://maps.googleapis.com/maps/api/streetview/metadata"

# How far around the target to look for neighbouring buildings when deciding
# whether a side extension has anywhere to go. Far enough to catch the
# attached neighbour and the one across the drive; not so far that the whole
# street lands in the test.
NEIGHBOUR_RADIUS_M = 45.0

# A side extension needs this much clear ground beyond its own width before
# it is offered — the gap a bricklayer needs to build the outer skin and get
# scaffold up, not a legal boundary distance.
SIDE_WORKING_CLEARANCE_M = 0.6

# Storey height used only when there is no LIDAR to difference. UK two-storey
# housing runs 2.4m floor to ceiling plus a 0.35m floor zone; the eaves of a
# 1930s semi land near 5.2m. Stated, never silently applied.
ASSUMED_STOREY_HEIGHT_M = 2.75
ASSUMED_CEILING_HEIGHT_M = 2.4

# An outline this small is not a house — it is a shed, a garage or a bad
# match, and roofing it as a dwelling would be a confident lie.
MIN_DWELLING_AREA_M2 = 25.0

# ...and one this big is not a house either. OpenStreetMap very often maps a
# terrace as ONE building way covering the whole row: live, 37 Mace Street
# came back as a single 758 m2, 54.5m-long polygon holding about ten houses,
# with no addr:housenumber anywhere in the response to split it by. Modelling
# that as a dwelling would put a ten-house block on the drawing and price it
# as one job, so a row is detected and handled as a row.
MAX_DWELLING_AREA_M2 = 250.0
MAX_DWELLING_FRONTAGE_M = 22.0

# Frontage of one bay of a UK terrace when nothing better is known. Two-up
# two-downs run 4.5-5.5m; this is the middle of that and is always reported
# as assumed, never as a measurement.
ASSUMED_BAY_WIDTH_M = 5.2

# Beyond this the "extension" is a second house and the single-span roof and
# the permitted-development framing both stop being true.
MAX_EXTENSION_M = 12.0


class ProposeError(RuntimeError):
    """The proposal cannot be made from what is actually known."""


# --- plan geometry ---------------------------------------------------------

def convex_hull(points):
    """Andrew's monotone chain. Returns the hull counter-clockwise."""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2:
                (ax, ay), (bx, by) = out[-2], out[-1]
                if (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax) > 0:
                    break
                out.pop()
            out.append(p)
        return out

    return half(pts)[:-1] + half(reversed(pts))[:-1]


def min_area_rect(polygon):
    """The smallest rectangle enclosing a footprint, and its orientation.

    A building's walls are straight and mostly square to each other, so the
    minimum-area enclosing rectangle recovers the wall directions even from
    an outline someone traced roughly off aerial imagery. Taking the axis
    from the longest edge instead — the tempting shortcut — swings the whole
    model by whatever error is in that one edge.

    Returns {angle_rad, width_m, depth_m, centre, area_m2}, where `angle_rad`
    is the direction of the rectangle's WIDTH axis in the input frame.
    """
    hull = convex_hull(polygon)
    if len(hull) < 3:
        raise ProposeError("the building outline has no area")

    best = None
    for i in range(len(hull)):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % len(hull)]
        theta = math.atan2(by - ay, bx - ax)
        c, s = math.cos(-theta), math.sin(-theta)
        xs = [p[0] * c - p[1] * s for p in hull]
        ys = [p[0] * s + p[1] * c for p in hull]
        w, d = max(xs) - min(xs), max(ys) - min(ys)
        area = w * d
        if best is None or area < best[0] - 1e-9:
            cx = (max(xs) + min(xs)) / 2.0
            cy = (max(ys) + min(ys)) / 2.0
            # Back out of the rotated frame to get the centre in world terms.
            wc, ws = math.cos(theta), math.sin(theta)
            best = (area, theta, w, d,
                    (cx * wc - cy * ws, cx * ws + cy * wc))

    area, theta, w, d, centre = best
    return {"angle_rad": theta, "width_m": round(w, 3),
            "depth_m": round(d, 3), "centre": centre,
            "area_m2": round(area, 2)}


# Cell size for decomposing an outline into rectangles. 0.5m is finer than
# the positional error in a traced OSM outline, so going smaller buys
# precision the source does not have.
DECOMP_CELL_M = 0.5

# A leftover piece smaller than this is outline noise — a chamfered corner, a
# bay a metre deep — not a part of the building worth its own block.
DECOMP_MIN_PIECE_M2 = 4.0

# ...and neither is a long thin strip. An area floor alone lets a 10m x 1m
# sliver through, which is what a slightly skewed outline leaves behind after
# the main rectangle is taken out. It is not an outrigger, it is the
# difference between the traced polygon and the axes, and modelling it puts a
# 1m-deep phantom room down the back of the house. A real block is at least
# this wide in BOTH directions.
DECOMP_MIN_SIDE_M = 2.0

# More blocks than this and the outline is not a house shape; the bounding
# rectangle is the more honest answer than a mosaic.
DECOMP_MAX_PIECES = 4


def _largest_rectangle(grid, w, h):
    """Biggest all-true axis-aligned rectangle in a binary grid.

    Standard largest-rectangle-in-histogram, run once per row. Returns
    (area, x0, y0, x1, y1) in cell indices, end-exclusive.
    """
    heights = [0] * w
    best = (0, 0, 0, 0, 0)
    for y in range(h):
        for x in range(w):
            heights[x] = heights[x] + 1 if grid[y][x] else 0
        # Monotonic stack over this row's histogram.
        stack = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            start = x
            while stack and stack[-1][1] >= cur:
                sx, sh = stack.pop()
                area = sh * (x - sx)
                if area > best[0]:
                    best = (area, sx, y - sh + 1, x, y + 1)
                start = sx
            stack.append((start, cur))
    return best


def decompose(polygon, cell_m=DECOMP_CELL_M):
    """An outline as a small set of rectangles, in its own local frame.

    A UK semi is rarely a box. It is a main block with a two-storey or
    single-storey outrigger off the back, and modelling it as its bounding
    rectangle inflates the floor area, buries the rear elevation and produces
    the featureless cube that makes a render worthless. Greedily pulling the
    largest rectangle out of a rasterised outline, repeatedly, recovers the
    L or T that is actually there.

    Input is a polygon already in the local plan frame (x along the front).
    Returns a list of (x, y, width, depth) in metres, largest first.
    """
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, y0 = min(xs), min(ys)
    w = max(1, int(math.ceil((max(xs) - x0) / cell_m)))
    h = max(1, int(math.ceil((max(ys) - y0) / cell_m)))
    if w * h > 40000:  # a 100m x 100m building is not what this is for
        return []

    grid = [[roofmod.point_in_polygon(x0 + (cx + 0.5) * cell_m,
                                      y0 + (cy + 0.5) * cell_m, polygon)
             for cx in range(w)] for cy in range(h)]

    pieces = []
    for _ in range(DECOMP_MAX_PIECES):
        area, ax, ay, bx, by = _largest_rectangle(grid, w, h)
        pw, pd = (bx - ax) * cell_m, (by - ay) * cell_m
        if area * cell_m * cell_m < DECOMP_MIN_PIECE_M2:
            break
        # Clear it either way: a sliver left in the grid is found again on
        # the next pass and the loop never advances.
        for cy in range(ay, by):
            for cx in range(ax, bx):
                grid[cy][cx] = False
        if min(pw, pd) < DECOMP_MIN_SIDE_M:
            continue
        pieces.append((round(x0 + ax * cell_m, 2), round(y0 + ay * cell_m, 2),
                       round(pw, 2), round(pd, 2)))
    return pieces


def clip_to_strip(polygon, x0, x1):
    """Sutherland-Hodgman clip of a polygon to the band x0 <= x <= x1.

    Cutting one house out of a mapped terrace row means cutting its outline
    too, or the decomposition sees the whole row's shape and the outrigger of
    number 41 turns up on number 37's plan.
    """
    def clip(poly, keep, at, axis_min):
        out = []
        for i in range(len(poly)):
            cur, prv = poly[i], poly[i - 1]
            cin, pin = keep(cur), keep(prv)
            if cin != pin:
                dx = cur[0] - prv[0]
                if abs(dx) > 1e-12:
                    t = (at - prv[0]) / dx
                    out.append((at, prv[1] + t * (cur[1] - prv[1])))
            if cin:
                out.append(cur)
        return out

    poly = [p for p in polygon]
    if poly and poly[0] == poly[-1]:
        poly = poly[:-1]
    poly = clip(poly, lambda p: p[0] >= x0, x0, True)
    if not poly:
        return []
    poly = clip(poly, lambda p: p[0] <= x1, x1, False)
    return poly


def rotate(point, angle, origin=(0.0, 0.0)):
    """Rotate a point about an origin by `angle` radians."""
    c, s = math.cos(angle), math.sin(angle)
    x, y = point[0] - origin[0], point[1] - origin[1]
    return (x * c - y * s + origin[0], x * s + y * c + origin[1])


def bearing_of(angle_rad):
    """Compass bearing for a direction given as a maths angle in the OS grid.

    Easting is x and northing is y, so a maths angle measured
    counter-clockwise from east becomes a bearing clockwise from north.
    """
    return (90.0 - math.degrees(angle_rad)) % 360.0


# --- which way the house faces ---------------------------------------------

def camera_position(lat, lon, key, radius_m=50):
    """Where Street View's nearest camera actually stands.

    Returns (lat, lon) or None. This is a metadata request — free, and it
    does not count against the imagery quota.
    """
    try:
        r = roofmod._requests().get(
            STREETVIEW_META,
            params={"location": f"{lat},{lon}", "radius": radius_m,
                    "source": "outdoor", "key": key},
            timeout=roofmod.HTTP_TIMEOUT)
        payload = r.json()
    except Exception as e:
        print(f"street view metadata failed: {e}", file=sys.stderr)
        return None
    if payload.get("status") != "OK":
        print(f"street view metadata: {payload.get('status')}",
              file=sys.stderr)
        return None
    loc = payload.get("location") or {}
    if loc.get("lat") is None:
        return None
    return (float(loc["lat"]), float(loc["lng"]))


# The four sides of the plan rectangle, named by the outward direction they
# face in the local frame. `front` is resolved to one of these.
SIDES = ("south", "north", "west", "east")
_SIDE_NORMAL = {"south": (0.0, -1.0), "north": (0.0, 1.0),
                "west": (-1.0, 0.0), "east": (1.0, 0.0)}


def choose_front(rect, camera_en):
    """Which side of the rectangle the road is on.

    `camera_en` is the Street View camera in the same (easting, northing)
    frame as the footprint. The front is the side whose outward normal points
    most nearly at it. With no camera the answer is None and the caller must
    say so rather than pick one.
    """
    if camera_en is None:
        return None
    cx, cy = rect["centre"]
    # Into the rectangle's own frame: undo its rotation about its centre.
    dx, dy = camera_en[0] - cx, camera_en[1] - cy
    c, s = math.cos(-rect["angle_rad"]), math.sin(-rect["angle_rad"])
    lx, ly = dx * c - dy * s, dx * s + dy * c
    n = math.hypot(lx, ly)
    if n < 1e-6:
        return None
    lx, ly = lx / n, ly / n
    return max(SIDES, key=lambda k: _SIDE_NORMAL[k][0] * lx
               + _SIDE_NORMAL[k][1] * ly)


def local_frame(rect, front):
    """A frame with the front elevation on y=0 and the house in +x, +y.

    model3d puts the front door on the y0 edge, so orienting the plan this
    way means the existing door-placement rule lands it on the real front of
    the real house instead of on whichever wall happened to sort first.

    Returns (angle_rad, origin_en, width_m, depth_m) where angle_rad rotates
    LOCAL into WORLD and origin_en is the local origin in eastings/northings.
    """
    w, d = rect["width_m"], rect["depth_m"]
    # Rotation taking the local +x axis onto the world direction that runs
    # along the chosen front, with the house on the +y side of it.
    turn = {"south": 0.0, "east": math.pi / 2,
            "north": math.pi, "west": -math.pi / 2}[front]
    angle = rect["angle_rad"] + turn
    if front in ("east", "west"):
        w, d = d, w
    # The local origin is the front-left corner: step back from the centre
    # half the width along +x and half the depth along +y.
    cx, cy = rect["centre"]
    ox = cx - (w / 2) * math.cos(angle) + (d / 2) * math.sin(angle)
    oy = cy - (w / 2) * math.sin(angle) - (d / 2) * math.cos(angle)
    return angle, (ox, oy), round(w, 3), round(d, 3)


def to_local(point_en, angle, origin_en):
    """World eastings/northings into the local plan frame."""
    dx, dy = point_en[0] - origin_en[0], point_en[1] - origin_en[1]
    c, s = math.cos(-angle), math.sin(-angle)
    return (dx * c - dy * s, dx * s + dy * c)


def to_world(point_local, angle, origin_en):
    """Local plan frame back out to eastings/northings."""
    c, s = math.cos(angle), math.sin(angle)
    x, y = point_local
    return (x * c - y * s + origin_en[0], x * s + y * c + origin_en[1])


# --- which side is free to build on ----------------------------------------

def neighbour_outlines(lat, lon, own_polygon, radius_m=NEIGHBOUR_RADIUS_M):
    """Every OTHER mapped building near the target, in eastings/northings.

    A side extension is only a proposal if there is ground to put it on, and
    the attached neighbour of a semi is the commonest reason there is not.
    This is what makes the side choice a measurement rather than a coin toss.
    """
    rings = roofmod._footprints_from_osm_api(lat, lon, radius_m)
    if not rings:
        return []
    own = _ring_key(own_polygon)
    out = []
    for ring in rings:
        poly = [roofmod.osgb.latlon_to_easting_northing(p["lat"], p["lon"])
                for p in ring]
        if _ring_key(poly) == own:
            continue
        out.append(poly)
    return out


def _ring_key(polygon):
    """A shape's identity, robust to where the ring starts and which way it
    winds — the same building fetched twice must compare equal."""
    pts = sorted((round(x, 1), round(y, 1)) for x, y in polygon)
    return tuple(pts)


def side_clearance(angle, origin_en, width, depth, side, neighbours,
                   probe_m=MAX_EXTENSION_M):
    """How far you can build out from one side before hitting a neighbour.

    Walks outward from the middle of that elevation in 0.25m steps and stops
    at the first step that lands inside another building. Returns metres.
    """
    step = 0.25
    if side == "east":
        start, direction = (width, depth / 2), (1.0, 0.0)
    elif side == "west":
        start, direction = (0.0, depth / 2), (-1.0, 0.0)
    elif side == "north":
        start, direction = (width / 2, depth), (0.0, 1.0)
    else:
        start, direction = (width / 2, 0.0), (0.0, -1.0)

    reach = 0.0
    while reach < probe_m:
        reach += step
        px = start[0] + direction[0] * reach
        py = start[1] + direction[1] * reach
        wx, wy = to_world((px, py), angle, origin_en)
        for poly in neighbours:
            if roofmod.point_in_polygon(wx, wy, poly):
                return round(reach - step, 2)
    return round(probe_m, 2)


# --- heights ---------------------------------------------------------------

def roof_from_solar(payload, span_m):
    """Pitch, ridge axis and the roof's own rise, from the Solar segments.

    The pitch is `predominant_pitch_deg` — solar.py's area-weighted median —
    and not the mean of the two biggest planes. That module documents a real
    roof where the largest single segment was a gable cheek at 57.8 degrees,
    17 degrees off the weighted figure, and taking the big planes at face
    value is exactly the mistake it was written to stop.

    `planeHeightAtCenterMeters` is the height at the MIDDLE of a sloping
    plane, which is halfway up the slope — so the ridge sits half the rise
    above it and the eaves half below. Reading it as the ridge puts the whole
    roof a metre high on a 35-degree semi.
    """
    parsed = solar.parse_segments(payload)
    if not parsed:
        return None
    planes = parsed.get("planes") or []
    pitched = [p for p in planes if not p["flat"] and p["sloped_area_m2"] > 0]
    if not pitched:
        return None

    pitch = parsed.get("predominant_pitch_deg")
    if pitch is None:
        return None
    rise = (span_m / 2.0) * math.tan(math.radians(pitch))

    # GABLE OR HIP IS IN THE DATA, AND IT WAS BEING IGNORED. Every proposal
    # hard-coded "hipped" while the segment list already said otherwise: a
    # gabled roof shows TWO pitched planes facing opposite ways, a hipped
    # roof shows four (or three with one hip end). The audit put a delivered
    # hipped box next to the owner's photograph of a gabled house with the
    # evidence for the gable sitting parsed and unread in this very payload.
    aspects = [p["aspect_deg"] for p in pitched
               if p["aspect_deg"] is not None]
    form = "hipped"
    if len(pitched) <= 2:
        form = "gabled"
        if len(aspects) == 2:
            spread = abs((aspects[0] - aspects[1] + 180) % 360 - 180)
            if spread < 120:
                # Two planes facing the SAME way is not a gable pair — it is
                # a complex roof seen partially. Do not over-claim.
                form = "hipped"
    form_source = (f"{len(pitched)} pitched plane(s) at "
                   + ", ".join(f"{a:.0f}" for a in aspects)
                   + " deg (Google Solar)")

    # The ridge runs across the slope, so the aspect of the largest pitched
    # plane fixes it. Small low segments are outriggers and porches.
    largest = max(pitched, key=lambda p: p["sloped_area_m2"])
    aspect = largest["aspect_deg"]
    heights = [s.get("planeHeightAtCenterMeters")
               for s in (payload.get("solarPotential") or {})
               .get("roofSegmentStats", [])
               if s.get("planeHeightAtCenterMeters") is not None]

    return {
        "pitch_deg": round(pitch, 1),
        "form": form,
        "form_source": form_source,
        "pitch_spread_deg": parsed.get("pitch_spread_deg"),
        "complex": parsed.get("complex"),
        "rise_m": round(rise, 2),
        # A roof slopes down the way it faces, so the ridge runs across that.
        "ridge_bearing_deg": (round((aspect + 90) % 180, 1)
                              if aspect is not None else None),
        "aspect_deg": aspect,
        "plane_height_od_m": round(max(heights), 2) if heights else None,
        "lower_plane_od_m": round(min(heights), 2) if heights else None,
        "segments": parsed.get("segments"),
        # Solar's own footprint, from a different measurement than the OSM
        # outline. Two independent sources for the same number is worth
        # carrying: when they disagree, the model is standing on sand.
        "solar_footprint_m2": parsed.get("footprint_m2"),
        "imagery_date": parsed.get("imagery_date"),
    }


def storey_count(roof_info, ceiling_h=ASSUMED_CEILING_HEIGHT_M):
    """Two storeys unless the roof says otherwise.

    Where Solar reports a main roof and a clearly lower one, the drop between
    them is a real measurement of how far the outrigger sits below the main
    eaves, and a drop near a full storey confirms two floors.
    """
    if not roof_info:
        return 2, "assumed"
    hi = roof_info.get("plane_height_od_m")
    lo = roof_info.get("lower_plane_od_m")
    if hi is None or lo is None or hi - lo < 1.0:
        return 2, "assumed"
    drop = hi - lo
    if drop >= ceiling_h * 0.8:
        return 2, "measured (main roof {}m above the lower roof)".format(
            round(drop, 2))
    return 2, "assumed"


# --- the extension ---------------------------------------------------------

# Below this a side extension is a corridor, not a room. If the measured
# clearance cannot take at least this, the side genuinely has nowhere to go
# and saying so beats designing a 900mm passage nobody asked for.
MIN_USEFUL_SIDE_M = 1.8


def place_extension(width, depth, brief, clearances,
                    storey_h=ASSUMED_STOREY_HEIGHT_M):
    """Where the extension goes, in the local plan frame.

    Returns (rooms, fit) — model3d.Room objects and a record of what the
    measured clearances did to the brief.

    A BRIEF THAT DOES NOT FIT IS NOT AN ERROR. The builder asked for 3m down
    the side; the neighbour is 2.75m away. Failing the job tells them
    nothing. Designing the 2.15m that does fit, and saying it was reduced and
    why, is the answer they can act on. The job only fails when even a usable
    room cannot go there — and then it names the alternative.
    """
    kind = (brief.get("type") or "rear").lower()
    ext_depth = float(brief.get("depth_m") or 3.5)
    if not 1.0 <= ext_depth <= MAX_EXTENSION_M:
        raise ProposeError(
            f"an extension {ext_depth}m deep is outside what this designs "
            f"(1 to {MAX_EXTENSION_M}m)")
    ext_h = float(brief.get("ceiling_height_m") or ASSUMED_CEILING_HEIGHT_M)
    # An extension is single-storey unless the brief asks for two. The house
    # around it may be two; the extension does not inherit that.
    ext_storeys = int(brief.get("storeys") or 1)
    if ext_storeys < 1 or ext_storeys > 3:
        raise ProposeError(
            f"{ext_storeys} storeys is not an extension this designs (1 to 3)")
    if ext_storeys > 1:
        # THE HOUSE'S OWN storey height, not the assumed one. The house is
        # built at the measured floor-to-floor (3.016m at Basons); an
        # extension defaulted to the assumed 2.75m sat 0.27m short on every
        # level, and the mismatch rendered as an open seam between storeys.
        ext_h = float(brief.get("ceiling_height_m") or storey_h)

    rooms, fit = [], {"type": kind, "requested": dict(brief),
                      "storeys": ext_storeys}
    if kind == "rear":
        w = min(float(brief.get("width_m") or width), width)
        allowed = clearances.get("north", MAX_EXTENSION_M)
        d = ext_depth
        if allowed < ext_depth:
            d = round(max(allowed, 0.0), 2)
            if d < 1.0:
                raise ProposeError(
                    f"the rear has {allowed}m of clear ground before the "
                    f"next building — there is nowhere to put a rear "
                    f"extension on this plot.")
            fit["reduced"] = (f"depth cut from {ext_depth}m to {d}m — "
                              f"{allowed}m measured clear to the rear")
        fit["built_m"] = {"width": round(w, 2), "depth": d}
        rooms.append(model3d.Room("extension", (width - w) / 2.0, depth,
                                  w, d, ext_h, kind="extension",
                                  storeys=ext_storeys))

    elif kind == "side":
        options = {s: clearances.get(s, 0.0) for s in ("east", "west")}
        side = brief.get("side")
        if side not in options:
            side = max(options, key=options.get)
        elif options[side] < options["west" if side == "east" else "east"] \
                and options[side] < MIN_USEFUL_SIDE_M:
            side = "west" if side == "east" else "east"
            fit["moved"] = f"asked for the other side; only {side} is open"

        want = float(brief.get("width_m") or ext_depth)
        buildable = round(max(options[side] - SIDE_WORKING_CLEARANCE_M, 0.0), 2)
        if buildable < MIN_USEFUL_SIDE_M:
            raise ProposeError(
                f"neither side has room for a usable extension — measured "
                f"clearance is {options['east']}m east and {options['west']}m "
                f"west, and after a {SIDE_WORKING_CLEARANCE_M}m working gap "
                f"that leaves under {MIN_USEFUL_SIDE_M}m to build in. This "
                f"plot supports a REAR extension; re-run with "
                f'"type": "rear".')
        room_w = min(want, buildable)
        if room_w < want:
            fit["reduced"] = (
                f"width cut from {want}m to {room_w}m — {options[side]}m "
                f"measured clear to the {side}, less a "
                f"{SIDE_WORKING_CLEARANCE_M}m working gap")
        d = min(float(brief.get("length_m") or depth), depth)
        x = width if side == "east" else -room_w
        fit["side"] = side
        fit["built_m"] = {"width": room_w, "depth": round(d, 2)}
        rooms.append(model3d.Room("extension", x, depth - d, room_w, d,
                                  ext_h, kind="extension",
                                  storeys=ext_storeys))

    elif kind == "wrap":
        w = min(float(brief.get("width_m") or width), width)
        rear_d = min(ext_depth, clearances.get("north", MAX_EXTENSION_M))
        if rear_d < 1.0:
            raise ProposeError(
                "the rear is blocked, so there is no wrap to design here.")
        fit["built_m"] = {"width": round(w, 2), "depth": round(rear_d, 2)}
        rooms.append(model3d.Room("extension", (width - w) / 2.0, depth,
                                  w, rear_d, ext_h, kind="extension",
                                  storeys=ext_storeys))
        side = max(("east", "west"), key=lambda s: clearances.get(s, 0.0))
        buildable = round(
            max(clearances.get(side, 0.0) - SIDE_WORKING_CLEARANCE_M, 0.0), 2)
        want = float(brief.get("return_width_m") or 2.5)
        room_w = min(want, buildable)
        if room_w >= MIN_USEFUL_SIDE_M:
            ret_d = min(3.0, depth)
            x = width if side == "east" else -room_w
            fit["return"] = {"side": side, "width": room_w,
                             "depth": round(ret_d + rear_d, 2)}
            rooms.append(model3d.Room("extension return", x, depth - ret_d,
                                      room_w, ret_d + rear_d, ext_h,
                                      kind="extension", storeys=ext_storeys))
        else:
            fit["return"] = (
                f"dropped — {clearances.get(side, 0.0)}m clear to the {side} "
                f"cannot take a usable return. Built as a rear extension.")
    elif kind == "over":
        # BEDROOMS ON TOP OF WHAT IS ALREADY THERE. The classic 1930s-semi
        # job: a single-storey garage, utility or side element down one
        # flank, and a first floor built over it. There is no new ground
        # floor, no new foundations to dig unless the existing ones fail the
        # check, and no ground taken from the plot — which is why it is the
        # answer on a tight site where a side extension has already been
        # refused for want of 1.8m.
        #
        # It is modelled as a block starting at level 1, so the quantities
        # count one floor and not two. Getting that wrong prices a ground
        # floor the client already owns.
        side = brief.get("side")
        options = {s: clearances.get(s, 0.0) for s in ("east", "west")}
        if side not in options:
            side = max(options, key=options.get)
        room_w = min(float(brief.get("width_m") or 3.2), width * 0.5)
        d = min(float(brief.get("length_m") or depth * 0.8), depth)
        # INSIDE the footprint, not beside it. Placed on the flank the first
        # version put it OUTSIDE the outline, where there is by definition
        # nothing underneath — the render showed a first floor hanging in
        # mid-air with daylight beneath it. "On top" means on top of
        # something, so the block sits over the existing house's own flank.
        x = (width - room_w) if side == "east" else 0.0
        fit["side"] = side
        fit["over_existing"] = True
        fit["built_m"] = {"width": round(room_w, 2), "depth": round(d, 2)}
        fit["base_level"] = 1
        rooms.append(model3d.Room("extension over", x, depth - d, room_w, d,
                                  ext_h, kind="extension",
                                  storeys=ext_storeys, base_level=1))
    else:
        raise ProposeError(
            f"unknown extension type {kind!r} — rear, side, wrap or over")
    return rooms, fit



# --- the house as it stands today ------------------------------------------

# Height bands for reading the mask+DSM into storeys. Between SINGLE_MIN and
# TALL_MIN a masked pixel is a single-storey structure (an addition, a
# garage); at TALL_MIN and above it belongs to the two-storey core or its
# roof. Below SINGLE_MIN it is a wall, a bin store or noise, and ignored.
BAND_SINGLE_MIN_M = 2.0
BAND_TALL_MIN_M = 4.2
EXIST_CELL_M = 0.25
EXIST_MAX_RECTS = 5
EXIST_MIN_SIDE_M = 1.5


def _utm_from_ll(lat, lon, epsg):
    """Lat/lon -> the UTM zone Solar's GeoTIFFs are delivered in."""
    zone = epsg - 32600
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians(zone * 6 - 183)
    lat, lon = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    T = math.tan(lat) ** 2
    C = ep2 * math.cos(lat) ** 2
    A = math.cos(lat) * (lon - lon0)
    M = a * ((1 - e2/4 - 3*e2**2/64 - 5*e2**3/256) * lat
             - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat)
             + (15*e2**2/256 + 45*e2**3/1024) * math.sin(4*lat)
             - (35*e2**3/3072) * math.sin(6*lat))
    E = k0*N*(A + (1-T+C)*A**3/6 + (5-18*T+T**2+72*C-58*ep2)*A**5/120) \
        + 500000.0
    Nn = k0*(M + N*math.tan(lat)*(A**2/2 + (5-T+9*C+4*C**2)*A**4/24
             + (61-58*T+T**2+600*C-330*ep2)*A**6/720))
    return E, Nn


def _grid_rects(cells, nx, ny, x0, y0, cell):
    """Greedy rectangle cover of a boolean lattice, in local metres."""
    grid = [[cells[cy][cx] for cx in range(nx)] for cy in range(ny)]
    rects = []
    for _ in range(EXIST_MAX_RECTS):
        area, ax, ay, bx, by = _largest_rectangle(grid, nx, ny)
        w, d = (bx - ax) * cell, (by - ay) * cell
        if area * cell * cell < EXIST_MIN_SIDE_M ** 2:
            break
        for cy in range(ay, by):
            for cx in range(ax, bx):
                grid[cy][cx] = False
        if min(w, d) < EXIST_MIN_SIDE_M:
            continue
        rects.append((round(x0 + ax * cell, 2), round(y0 + ay * cell, 2),
                      round(w, 2), round(d, 2)))
    return rects


def existing_from_solar(grid, pin_ll, angle, origin_en, width, depth,
                        storey_h):
    """The existing house read off Solar's mask + DSM, as measured blocks.

    OpenStreetMap draws the ORIGINAL outline; owners build. At 3 Basons
    Lane the mapped pair is 95.8m2 of 1930s footprint while the mask shows
    the front porch band and the side addition the owner actually built —
    and an extension designed against the mapped outline lands on top of
    them. This samples the height field over the slice and its outward
    flank, keeps what is connected to the core, and returns
    (two_storey_rects, single_rects, single_h, coverage_note) in the local
    frame — or None when the data cannot say (no grid, core unmasked).

    The party-wall side is clipped at x=0: whatever stands across it is the
    neighbour's, however similar its height reads.
    """
    if not grid:
        return None
    import numpy as np
    agl = grid["agl"]
    sx, ox, sy, oy = grid["transform"]
    epsg = grid["utm_epsg"]
    lat0, lon0 = pin_ll
    e0, n0 = roofmod.osgb.latlon_to_easting_northing(lat0, lon0)
    coslat = math.cos(math.radians(lat0))

    xs0, xs1 = -0.05, width + 7.0        # party wall .. outward flank
    ys0, ys1 = -2.5, depth + 8.0
    cell = EXIST_CELL_M
    nx = int((xs1 - xs0) / cell)
    ny = int((ys1 - ys0) / cell)
    H, W = agl.shape
    height = [[float("nan")] * nx for _ in range(ny)]
    for cy in range(ny):
        for cx in range(nx):
            e, n = to_world((xs0 + (cx + 0.5) * cell,
                             ys0 + (cy + 0.5) * cell), angle, origin_en)
            lat = lat0 + (n - n0) / 111320.0
            lon = lon0 + (e - e0) / (111320.0 * coslat)
            E, N = _utm_from_ll(lat, lon, epsg)
            col = int((E - ox) / sx)
            row = int((N - oy) / sy)
            if 0 <= row < H and 0 <= col < W:
                height[cy][cx] = float(agl[row, col])

    def band(lo, hi):
        return [[(not math.isnan(height[cy][cx]))
                 and lo <= height[cy][cx] < hi
                 for cx in range(nx)] for cy in range(ny)]
    tall = band(BAND_TALL_MIN_M, 99.0)
    single = band(BAND_SINGLE_MIN_M, BAND_TALL_MIN_M)
    built = [[tall[cy][cx] or single[cy][cx] for cx in range(nx)]
             for cy in range(ny)]

    # Keep only what is CONNECTED to the mapped core: the neighbour behind
    # the garden reads as built too, and without this it becomes a wing.
    keep = [[False] * nx for _ in range(ny)]
    stack = []
    for cy in range(ny):
        for cx in range(nx):
            lx = xs0 + (cx + 0.5) * cell
            ly = ys0 + (cy + 0.5) * cell
            if built[cy][cx] and 0 <= lx <= width and 0 <= ly <= depth:
                keep[cy][cx] = True
                stack.append((cy, cx))
    if not any(any(row) for row in keep):
        return None
    while stack:
        cy, cx = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny_, nx_ = cy + dy, cx + dx
            if 0 <= ny_ < ny and 0 <= nx_ < nx and built[ny_][nx_] \
                    and not keep[ny_][nx_]:
                keep[ny_][nx_] = True
                stack.append((ny_, nx_))

    tall_k = [[tall[cy][cx] and keep[cy][cx] for cx in range(nx)]
              for cy in range(ny)]
    single_k = [[single[cy][cx] and keep[cy][cx] for cx in range(nx)]
                for cy in range(ny)]
    tall_rects = _grid_rects(tall_k, nx, ny, xs0, ys0, cell)
    single_rects = _grid_rects(single_k, nx, ny, xs0, ys0, cell)
    if not tall_rects:
        return None
    singles_h = [height[cy][cx] for cy in range(ny) for cx in range(nx)
                 if single_k[cy][cx]]
    singles_h.sort()
    single_h = None
    if singles_h:
        # Median roof level of the additions, less a nominal 300mm of deck
        # and upstand, is the storey below it — clamped to buildable.
        single_h = max(2.2, min(3.2, singles_h[len(singles_h)//2] - 0.3))
    core = sum(r[2] * r[3] for r in tall_rects)
    addn = sum(r[2] * r[3] for r in single_rects)
    note = (f"existing house measured from the height field: two-storey "
            f"core {core:.0f}m2, single-storey additions {addn:.0f}m2 "
            f"({grid['source']})")
    return tall_rects, single_rects, single_h, note


# --- assembly --------------------------------------------------------------

def ext_span_x(rooms):
    """How far the extension blocks push the plan out along x."""
    if not rooms:
        return 0.0
    return max(r.x + r.width for r in rooms) - min(min(r.x for r in rooms),
                                                   0.0)


def run(spec, prog, output_dir):
    """Address in, a measured 3D proposal out."""
    prog.stage("locating")
    location = roofmod.resolve_location(spec)
    lat, lon = location["lat"], location["lon"]
    prog.note(f"{lat:.6f}, {lon:.6f} — {location['grid_ref']}")

    prog.stage("footprint")
    polygon = roofmod.fetch_footprint(lat, lon, radius_m=40)
    if not polygon:
        raise ProposeError(
            "no building outline is mapped at this location, so there is "
            "nothing to extend. Supply gps for the building itself, or a "
            "footprint, and this will design against it.")
    measured_area = abs(roofmod.polygon_area(polygon))
    if measured_area < MIN_DWELLING_AREA_M2:
        raise ProposeError(
            f"the outline here is {measured_area:.0f}m2 — too small to be "
            f"the dwelling. This is most likely a garage or an outbuilding; "
            f"pass gps on the house itself.")
    rect = min_area_rect(polygon)
    prog.note(f"outline {measured_area:.0f}m2, "
              f"{rect['width_m']}m x {rect['depth_m']}m")
    is_row = (measured_area > MAX_DWELLING_AREA_M2
              or max(rect["width_m"], rect["depth_m"])
              > MAX_DWELLING_FRONTAGE_M)

    prog.stage("orientation")
    keys = _keys()
    camera = camera_position(lat, lon, keys.get("maps")) if keys.get("maps") \
        else None
    camera_en = (roofmod.osgb.latlon_to_easting_northing(*camera)
                 if camera else None)
    front = choose_front(rect, camera_en)
    front_source = "street view camera position"
    if front is None:
        # Without the road there is no measured front. The long elevation is
        # the convention for a terrace or a semi, and saying so is the point.
        front = "south" if rect["width_m"] >= rect["depth_m"] else "west"
        front_source = "assumed (no street view coverage)"
    angle, origin_en, width, depth = local_frame(rect, front)
    prog.note(f"front elevation faces {bearing_of(angle - math.pi / 2):.0f}"
              f" degrees — {front_source}")

    # A mapped row is not a dwelling. Cut one bay out of it when the caller
    # pointed at an actual house; refuse plainly when all we have is the
    # postcode centroid, which lands somewhere in the middle of the row and
    # cannot pick a number.
    bay = None
    if is_row:
        explicit = isinstance(spec.get("gps"), dict) \
            and spec["gps"].get("lat") is not None
        if not explicit:
            raise ProposeError(
                f"OpenStreetMap maps this as ONE building {rect['width_m']}m "
                f"long and {measured_area:.0f}m2 in area — that is the whole "
                f"terrace row, not one house, and the map carries no house "
                f"numbers here to split it by. A postcode centroid cannot "
                f"pick a number out of a row. Pass gps for the house itself "
                f'({{"gps": {{"lat": ..., "lon": ...}}}}) and this will '
                f"design against its bay.")
        bay_w = float((spec.get("extension") or {}).get("bay_width_m")
                      or ASSUMED_BAY_WIDTH_M)
        here = to_local(
            roofmod.osgb.latlon_to_easting_northing(lat, lon),
            angle, origin_en)
        x0 = min(max(here[0] - bay_w / 2.0, 0.0), max(width - bay_w, 0.0))
        bay = {"x0": round(x0, 2), "width_m": round(min(bay_w, width), 2),
               "row_width_m": width, "row_area_m2": round(measured_area, 1)}
        # Re-origin the local frame on the bay so the house sits at x=0 and
        # every downstream rectangle is in the bay's own coordinates.
        origin_en = to_world((x0, 0.0), angle, origin_en)
        width = bay["width_m"]
        prog.note(f"terrace row {bay['row_width_m']}m long — taking a "
                  f"{width}m bay at {bay['x0']}m along it")

    # A SEMI PAIR IS A ROW OF TWO, AND THE MAP CANNOT SEE THE JOIN.
    # OpenStreetMap holds many pairs (and short terraces) as ONE outline of
    # dwelling-ish size, so the row gate above never fires: at 3 Basons Lane
    # the "building" was 12.1m x 7.9m, 95.8m2, and the whole pair was
    # modelled as one house — with the extension drawn across the
    # neighbour's half too. Google Solar segments the single dwelling
    # nearest the point, so when its measured footprint is a clean fraction
    # of the mapped outline, the outline is that many houses, and Solar's
    # building centre says which slice is the one at the pin. The halves
    # are assumed equal — that assumption is written into the provenance.
    solar_payload = None
    if bay is None and solar.available():
        try:
            solar_payload = solar.fetch_building_insights(lat, lon)
            whole = ((solar_payload or {}).get("solarPotential") or {}) \
                .get("wholeRoofStats") or {}
            sol_m2 = whole.get("groundAreaMeters2")
            centre = (solar_payload or {}).get("center") or {}
            if sol_m2 and centre.get("latitude") is not None:
                n = max(1, round(measured_area / sol_m2))
                strip_w = width / n
                if n >= 2 and strip_w >= 4.0:
                    cx = to_local(roofmod.osgb.latlon_to_easting_northing(
                        centre["latitude"], centre["longitude"]),
                        angle, origin_en)[0]
                    i = min(max(int(cx // strip_w), 0), n - 1)
                    bay = {"x0": round(i * strip_w, 2),
                           "width_m": round(strip_w, 2),
                           "row_width_m": width,
                           "row_area_m2": round(measured_area, 1),
                           "split_source": (
                               f"google solar measures this dwelling at "
                               f"{sol_m2:.0f}m2 inside a {measured_area:.0f}"
                               f"m2 mapped outline — a row of {n}, split "
                               f"equally, taking the slice under its "
                               f"building centre")}
                    origin_en = to_world((bay["x0"], 0.0), angle, origin_en)
                    width = bay["width_m"]
                    prog.note(
                        f"the mapped outline is {n} dwellings (solar "
                        f"{sol_m2:.0f}m2 vs outline {measured_area:.0f}m2) "
                        f"— taking the {width}m slice at {bay['x0']}m")
        except Exception as e:
            print(f"pair split skipped: {type(e).__name__}: {e}",
                  file=sys.stderr)

    prog.stage("clearances")
    others = neighbour_outlines(lat, lon, polygon)
    clearances = {s: side_clearance(angle, origin_en, width, depth, s, others)
                  for s in SIDES}
    if bay:
        # Both flanks of a mid-row bay are party walls, and the probe cannot
        # see them: the houses either side belong to the SAME OpenStreetMap
        # way, which is excluded as the target's own outline. Left to itself
        # the probe reports 12m of open ground down both sides of a terrace.
        left_gap = bay["x0"]
        right_gap = bay["row_width_m"] - (bay["x0"] + width)
        if left_gap > 0.5:
            clearances["west"] = 0.0
        if right_gap > 0.5:
            clearances["east"] = 0.0
        prog.note(f"party walls: west {'yes' if left_gap > 0.5 else 'no'}, "
                  f"east {'yes' if right_gap > 0.5 else 'no'}")
    prog.note(f"{len(others)} neighbouring outlines; clear east "
              f"{clearances['east']}m, west {clearances['west']}m, rear "
              f"{clearances['north']}m")

    prog.stage("roof")
    roof_info = None
    if solar.available():
        try:
            payload = solar_payload or solar.fetch_building_insights(lat, lon)
            roof_info = roof_from_solar(payload, min(width, depth))
        except Exception as e:
            print(f"solar insights unavailable: {e}", file=sys.stderr)
    if roof_info:
        prog.note(f"roof {roof_info['pitch_deg']} degrees, "
                  f"{roof_info.get('form','?')}, over "
                  f"{roof_info['segments']} segments")
    storeys, storeys_source = storey_count(roof_info)

    # MEASURE the building's height rather than assuming it. The DSM gives
    # ridge-above-ground directly; the pitch gives the roof's own rise; what
    # is left below the eaves is the walls, and dividing by the storey count
    # gives a MEASURED floor-to-floor. The 2.75m figure survives only as the
    # fallback, and the provenance says which one you got.
    heights = solar.measure_heights(lat, lon) if solar.available() else None
    storey_h = ASSUMED_STOREY_HEIGHT_M
    height_source = f"assumed {ASSUMED_STOREY_HEIGHT_M}m floor to floor"
    if heights and roof_info:
        span = min(width, depth)
        rise = (span / 2.0) * math.tan(
            math.radians(roof_info["pitch_deg"]))
        eaves_agl = heights["ridge_agl_m"] - rise
        candidate = eaves_agl / max(storeys, 1)
        # A measured storey outside plausible construction means the mask
        # caught a neighbour or the pitch disagrees with the DSM — keep the
        # assumption and say so rather than building a 1.4m-storey house.
        if 2.2 <= candidate <= 3.6:
            storey_h = round(candidate, 3)
            height_source = (
                f"measured: ridge {heights['ridge_agl_m']}m above ground "
                f"({heights['source']}), less a {rise:.2f}m roof rise at "
                f"{roof_info['pitch_deg']} degrees, over {storeys} storeys")
            prog.note(f"heights measured: ridge {heights['ridge_agl_m']}m, "
                      f"storey {storey_h}m")
        else:
            height_source = (
                f"assumed {ASSUMED_STOREY_HEIGHT_M}m — DSM gave an "
                f"implausible {candidate:.2f}m storey, so the measurement "
                f"was refused")

    # READ THE FACADE OFF THE PHOTO. The camera position was already being
    # used; the pixels were not, and they show every window, the door, the
    # bay and the chimney. Positions are approximate and say so — but they
    # are the real house's, which the rule could never be.
    facade = None
    facade_photo = None
    if camera and (spec.get("extension") or {}).get("facade") is not False:
        gem = os.environ.get("GOOGLE_AI_API_KEY", "")
        if gem and keys.get("maps"):
            try:
                import imagery
                # AIM AT THE BUILDING, NOT ALONG ITS FRONT. Aiming down the
                # front normal assumes the camera stands square-on; Street
                # View's nearest pano is routinely off to one side, and the
                # normal-aimed shot then frames the NEIGHBOUR — at 3 Basons
                # Lane it framed no. 5 while no. 3 sat at the photo's edge,
                # and every read downstream described the wrong house. The
                # bearing from the camera to the building's own centre hits
                # the right house from wherever the camera stands.
                bce, bcn = to_world((width / 2.0, depth / 2.0), angle,
                                    origin_en)
                ce, cn = camera_en
                heading = (math.degrees(math.atan2(bce - ce, bcn - cn))
                           + 360.0) % 360.0
                facade_photo = os.path.join(output_dir,
                                            f"{spec.get('scan_id') or 'x'}"
                                            f".facade.jpg")
                got = imagery.fetch_photo(camera[0], camera[1], heading,
                                          keys["maps"], facade_photo)
                if got:
                    facade = imagery.read_facade(got, gem)
                    if facade:
                        prog.note(
                            f"facade read from imagery: "
                            f"{len(facade['openings'])} openings, "
                            f"finish {facade.get('finish')}, chimney "
                            f"{'yes' if facade.get('chimney') else 'no'}")
            except Exception as e:
                print(f"facade read skipped: {type(e).__name__}: {e}",
                      file=sys.stderr)

    prog.stage("designing")
    brief = spec.get("extension") or {}
    # The existing house as the blocks actually in the outline, not as one
    # bounding box. Falls back to the box when the outline is already
    # rectangular or too ragged to decompose.
    local_poly = [to_local(p, angle, origin_en) for p in polygon]
    plan_area = measured_area
    if bay:
        local_poly = clip_to_strip(local_poly, 0.0, width)
        plan_area = abs(roofmod.polygon_area(local_poly)) if local_poly else 0.0
    pieces = decompose(local_poly) if local_poly else []
    covered = sum(p[2] * p[3] for p in pieces)
    if len(pieces) > 1 and covered >= plan_area * 0.75:
        house_rooms = [
            model3d.Room("existing house" if i == 0 else f"existing block {i}",
                         px, py, pw, pd, storey_h,
                         kind="existing")
            for i, (px, py, pw, pd) in enumerate(pieces)]
        plan_source = (f"{len(pieces)} blocks from the outline, "
                       f"{covered:.0f}m2 of {plan_area:.0f}m2")
    else:
        house_rooms = [model3d.Room("existing house", 0.0, 0.0, width, depth,
                                    storey_h, kind="existing")]
        plan_source = "bounding rectangle of the outline"

    # THE HOUSE AS IT STANDS TODAY, when the height field can see it. The
    # mapped outline is the house as first built; the mask + DSM show what
    # is actually there now — including the flat-roofed additions an
    # extension must build BEHIND, not through.
    exist_rear_y = depth
    if solar.available():
        try:
            sgrid = solar.surface_grid(lat, lon)
            found = existing_from_solar(sgrid, (lat, lon), angle, origin_en,
                                        width, depth, storey_h)
            if found:
                tall_rects, single_rects, single_h, note = found
                house_rooms = [
                    model3d.Room("existing house" if i == 0
                                 else f"existing block {i}",
                                 px, py, pw, pd, storey_h, kind="existing")
                    for i, (px, py, pw, pd) in enumerate(tall_rects)]
                for i, (px, py, pw, pd) in enumerate(single_rects):
                    house_rooms.append(model3d.Room(
                        f"existing addition {i}", px, py, pw, pd,
                        single_h or 2.6, kind="existing", storeys=1))
                exist_rear_y = max(r.y + r.depth for r in house_rooms)
                plan_source = note
                prog.note(note)
        except Exception as e:
            print(f"existing-from-solar skipped: {type(e).__name__}: {e}",
                  file=sys.stderr)
    prog.note(f"existing plan: {plan_source}")

    # Bays read off the photo become real projecting geometry.
    bay_rooms = []
    if facade:
        import imagery
        _, photo_bays = imagery.to_wall_openings(facade, width)
        for i, b in enumerate(photo_bays[:2]):
            bw = max(1.8, min(b["width"], 4.5))
            bx = max(0.0, min(b["x"], width - bw))
            # A bay the photo shows on both floors is built through both:
            # full storey height per level, its cap up at the eaves.
            n = max(1, min(int(b.get("storeys") or 1), 2))
            bay_rooms.append(model3d.Room(
                f"bay {i}", bx, -0.9, bw, 0.9,
                storey_h if n > 1 else 2.35, kind="existing",
                storeys=n))

    ext_rooms, fit = place_extension(width, depth, brief, clearances,
                                     storey_h=storey_h)
    # A rear extension starts where the house actually ENDS. The placement
    # works in the mapped outline's frame (rear at y=depth); when the
    # height field found additions standing beyond that line, the new work
    # shifts back to clear them instead of being drawn through them.
    if exist_rear_y > depth + 0.05:
        shift = exist_rear_y - depth
        for r in ext_rooms:
            if r.y >= depth - 0.05:
                r.y = round(r.y + shift, 3)
        fit["behind_existing"] = (
            f"the height field shows existing structures to "
            f"{exist_rear_y:.1f}m — the extension starts behind them, "
            f"{shift:.1f}m further back than the mapped outline suggested")
        prog.note(fit["behind_existing"])
    rooms = house_rooms + bay_rooms + ext_rooms
    if fit.get("reduced"):
        prog.note(fit["reduced"])
    built = fit.get("built_m") or {}
    prog.note(f"extension {built.get('width')}m x {built.get('depth')}m "
              f"({fit['type']})")

    roof_spec = None
    if roof_info:
        # The ridge runs along whichever plan axis it is more nearly parallel
        # to. Local +x lies along the front elevation, so comparing the two
        # bearings in the LOCAL frame is what decides it.
        ridge_local = None
        if roof_info["ridge_bearing_deg"] is not None:
            front_bearing = bearing_of(angle)
            delta = abs((roof_info["ridge_bearing_deg"] - front_bearing + 90)
                        % 180 - 90)
            ridge_local = "x" if delta < 45 else "y"

        # A RIDGE THAT FORCES PARALLEL RANGES IS ALMOST CERTAINLY THE WRONG
        # AXIS. roof_over splits any span wider than one roof can carry into
        # parallel ranges with valley gutters between them. That is a real
        # form and a rare one, and deriving it from a four-segment azimuth
        # estimate is over-claiming — on a 16.4m-wide house with a side
        # extension it produced TWO square hipped ranges, which hip down to
        # two pyramids sat next to each other. A valley gutter is also a
        # maintenance liability nobody should be proposed by accident.
        #
        # So: if the chosen axis needs more than one range and the other axis
        # spans in one, take the single span. A UK house ridges parallel to
        # its frontage, over the front-to-back depth, and that is the answer
        # this recovers.
        full_w = width + (ext_span_x(ext_rooms) if ext_rooms else 0.0)
        span_if_x = depth
        span_if_y = max(full_w, width)
        cap = model3d.MAX_ROOF_SPAN_M
        if ridge_local == "y" and span_if_y > cap and span_if_x <= cap:
            ridge_local = "x"
            prog.note(f"ridge axis corrected to run along the frontage — "
                      f"across the {span_if_y:.1f}m width it would have "
                      f"needed parallel ranges with a valley")
        roof_spec = {"pitch_deg": roof_info["pitch_deg"],
                     "kind": roof_info.get("form") or "hipped",
                     "ridge_along": ridge_local}

    model = model3d.build(rooms, storeys=storeys,
                          storey_height=storey_h,
                          roof=roof_spec)

    facade_note = "placed by rule — not surveyed"
    if facade:
        import imagery
        photo_ops, _ = imagery.to_wall_openings(facade, width)
        res = model3d.apply_facade_openings(model, photo_ops, facade_y=0.0)
        if res.get("applied"):
            facade_note = (
                f"front: {res['applied']} openings read from Street View "
                f"imagery (positions approximate, verify on site)"
                + (", rule door kept" if res.get("door_preserved") else "")
                + "; sides and rear remain placed by rule")
            model["facade"] = {"finish": facade.get("finish"),
                              "chimney": facade.get("chimney"),
                              "read": res}
            prog.note(facade_note)

    model["site"] = {
        "address": spec.get("address"),
        "gps": {"lat": lat, "lon": lon},
        "grid_ref": location["grid_ref"],
        "footprint_area_m2": round(measured_area, 1),
        "plan_m": {"width": width, "depth": depth},
        "front_faces": front,
        "front_bearing_deg": round(bearing_of(angle - math.pi / 2), 1),
        "front_source": front_source,
        "clearances_m": clearances,
        "neighbours_found": len(others),
        # The frame itself, so anything downstream can put a local plan
        # coordinate back on the map — the capture plan needs real GPS for
        # every shot, not a diagram.
        "frame": {
            "angle_rad": round(angle, 9),
            "origin_en": [round(origin_en[0], 3), round(origin_en[1], 3)],
            "anchor_en": [round(location["easting"], 3),
                          round(location["northing"], 3)],
        },
    }
    model["extension_fit"] = fit
    model["site"]["existing_plan_source"] = plan_source
    if bay:
        model["site"]["terrace_bay"] = bay

    # Anything the two independent sources disagree about, or that had to be
    # assumed, is collected here rather than buried in the geometry. A
    # builder reading one list knows exactly which numbers to check on site.
    checks = []
    if roof_info and roof_info.get("solar_footprint_m2"):
        # Compare like with like. Solar's findClosest returns ONE building,
        # so on a terrace it must be checked against the bay that was cut,
        # not against the whole mapped row — otherwise a correct 5.2m bay
        # reports a 1229% disagreement and the warning becomes noise.
        osm = plan_area if bay else measured_area
        sol = roof_info["solar_footprint_m2"]
        gap = abs(osm - sol) / max(sol, 1) * 100
        model["site"]["footprint_cross_check"] = {
            "openstreetmap_m2": round(osm, 1), "solar_m2": sol,
            "compared": "bay" if bay else "whole outline",
            "difference_pct": round(gap, 1),
        }
        if gap >= 15.0:
            checks.append(
                f"The two footprint sources disagree by {gap:.0f}% "
                f"({'bay cut from the map' if bay else 'OpenStreetMap'} "
                f"{osm:.0f}m2, Google Solar {sol:.0f}m2). Usually the mapped "
                f"outline includes an attached garage, or the bay width is "
                f"off. MEASURE THE FOOTPRINT ON SITE before this drives a "
                f"quote.")
    if roof_info and roof_info.get("complex"):
        checks.append(
            f"The roof spans {roof_info['pitch_spread_deg']} degrees of "
            f"pitch across {roof_info['segments']} segments, so the single "
            f"{roof_info['pitch_deg']}-degree figure is indicative, not one "
            f"measured plane.")
    if bay:
        checks.append(
            f"This house was cut as an assumed {bay['width_m']}m bay out of "
            f"a {bay['row_width_m']}m terrace row, because the map holds the "
            f"row as one building with no house numbers. MEASURE THE "
            f"FRONTAGE — every quantity scales directly off it.")
    if front_source.startswith("assumed"):
        checks.append(
            "No Street View coverage here, so which elevation is the front "
            "was assumed from the plan shape. If it is wrong, the front door "
            "and the extension are on the wrong side.")
    model["check_on_site"] = checks
    model["provenance"] = {
        "outline": "OpenStreetMap building way",
        "roof_pitch": ("Google Solar buildingInsights"
                       if roof_info else "not available — flat top modelled"),
        "orientation": front_source,
        "storeys": storeys_source,
        "roof_form": (roof_info.get("form_source")
                      if roof_info else "not measured"),
        "storey_height": height_source,
        "openings": facade_note,
        "plan": plan_source,
    }
    if bay:
        model["provenance"]["frontage"] = (
            f"assumed {bay['width_m']}m bay cut from a mapped "
            f"{bay['row_width_m']}m row")
    if roof_info:
        model["roof_measured"] = roof_info
    model["warning"] = (
        "This is a measured PROPOSAL, not a survey. The outline, roof pitch "
        "and orientation are from open data; window and door positions on "
        "the existing house are placed by rule. Check on site before "
        "ordering or building.")

    prog.stage("exporting")
    scan = spec.get("scan_id") or "proposal"
    artifacts = model3d._export_artifacts(model, output_dir, scan)

    # Ship pictures alongside the files. A GLB proves nothing to the person
    # holding the phone, and every geometry fault this mode has had was
    # obvious in a render and invisible in the quantities.
    shots = []
    try:
        import preview
        shots = preview.views(model, output_dir, scan)
        artifacts += shots
        model["previews"] = [os.path.basename(p) for p, _, _ in shots]
    except Exception as e:
        print(f"previews skipped: {type(e).__name__}: {e}", file=sys.stderr)
        model["previews"] = []

    # Cycles, if a Blender is reachable. The flat-shaded preview above is
    # always produced and is what the job guarantees; these are the same
    # geometry lit properly, and a worker without Blender simply does not
    # get them. `render_python` points at the interpreter holding the bpy
    # wheel, which is deliberately not this one — it pins numpy<2.
    glb = next((p for p, _, _ in artifacts if p.endswith(".glb")), None)
    if glb and (spec.get("extension") or {}).get("cycles") is not False:
        try:
            import blend
            ok, why = blend.available(spec.get("render_python"))
            if ok:
                prog.stage("rendering")
                # The hero angle keeps its silhouette mask — that mask is
                # what lets the photoreal pass be bounded by the geometry
                # instead of asked nicely to respect it.
                hero_mask = os.path.join(output_dir, f"{scan}.mask.png")
                blend.render(glb, os.path.join(
                    output_dir, f"{scan}.corner.cycles.png"),
                    yaw_deg=35, pitch_deg=16,
                    python=spec.get("render_python"), keep_mask=hero_mask)
                shots_hq = [(os.path.join(
                    output_dir, f"{scan}.corner.cycles.png"),
                    f"renders/{scan}.corner.cycles.png", None)]
                shots_hq += blend.views(
                    glb, output_dir, scan, angles=((215, 20), (0, 6)),
                    python=spec.get("render_python"))
                artifacts += shots_hq
                model["cycles_renders"] = [os.path.basename(p)
                                           for p, _, _ in shots_hq]
                model["_hero_src"] = shots_hq[0][0]
                model["_hero_mask"] = hero_mask
                prog.note(f"{len(shots_hq)} Cycles renders")
            else:
                model["cycles_renders"] = []
                print(f"cycles skipped: {why}", file=sys.stderr)
        except Exception as e:
            model["cycles_renders"] = []
            print(f"cycles skipped: {type(e).__name__}: {e}", file=sys.stderr)

    # The photoreal pass, driven BY the measured render so the geometry
    # cannot be renegotiated. Off with photoreal=false; it costs a few pence
    # a job and some callers only want the model.
    if shots and (spec.get("extension") or {}).get("photoreal") is not False:
        import hero
        prog.stage("photoreal")
        # Prefer the Cycles hero and its silhouette mask when they exist;
        # fall back to the flat preview, which has no mask and therefore
        # falls back to the guard-and-reject behaviour.
        src = model.get("_hero_src") or shots[0][0]
        hero_arts, note = hero.make(
            model, src, output_dir, scan,
            time_of_day=(spec.get("extension") or {}).get("light", "day"),
            mask_path=model.get("_hero_mask"))
        artifacts += hero_arts
        model["photoreal"] = note
        prog.note(note)

    # What the homeowner has to film for the scan half of the pipeline. It
    # is built here because it depends on the measurements this mode just
    # took — the standoff comes from the ridge height, and which elevations
    # are reachable at all comes from the probed clearances.
    try:
        import capture
        model["capture_plan"] = capture.plan(model, lat, lon)
        prog.note(f"capture plan: {model['capture_plan']['total_frames']} "
                  f"frames at {model['capture_plan']['standoff_m']}m standoff"
                  + (f", {len(model['capture_plan']['blocked'])} elevation(s) "
                     f"unreachable" if model["capture_plan"]["blocked"] else ""))
    except Exception as e:
        print(f"capture plan skipped: {type(e).__name__}: {e}", file=sys.stderr)

    # The before/after a client actually reacts to: the extension montaged
    # onto the real photo, sized from the survey. This was the best-received
    # output the project ever produced and it was being made BY HAND outside
    # the product — now it ships with the job, and the note carries Google's
    # attribution requirement with it.
    if facade_photo and os.path.exists(facade_photo)             and (spec.get("extension") or {}).get("montage") is not False:
        gem = os.environ.get("GOOGLE_AI_API_KEY", "")
        if gem:
            try:
                import hero as hero_mod
                after = os.path.join(output_dir, f"{scan}.after.png")
                _, mnote = hero_mod.montage_on_photo(
                    facade_photo, model.get("extension_fit") or {}, gem,
                    after)
                artifacts.append((facade_photo,
                                  f"renders/{scan}.before.jpg", None))
                artifacts.append((after, f"renders/{scan}.after.png", None))
                model["montage"] = mnote
                prog.note("before/after montage delivered")
            except Exception as e:
                print(f"montage skipped: {type(e).__name__}: {e}",
                      file=sys.stderr)

    for k in ("_hero_src", "_hero_mask"):
        model.pop(k, None)
    # ARTIFACTS FIRST — the handler contract is run() -> (artifacts, extra),
    # the order roof.py set and delivery expects. Reversed, the result dict
    # walks into deliver_many (which iterates its keys as "paths") and the
    # artifact tuples walk into result.update(), which throws on 3-tuples.
    # That exact failure reached the live endpoint on the first deployed
    # propose job, because every local run called this function directly.
    return artifacts, model


def _keys():
    """The API keys this mode can use. Street View is optional — without it
    the front elevation is assumed and the output says so."""
    return {
        "maps": (os.environ.get("GOOGLE_MAPS_API_KEY")
                 or os.environ.get("GOOGLE_SOLAR_API_KEY") or ""),
        "solar": os.environ.get("GOOGLE_SOLAR_API_KEY", ""),
    }
