"""Services Mode — the X-ray. Pipes and cables recovered from an open scan.

The wedge, and the thing this whole product was described around: see what is
behind the wall. Cameras and LiDAR cannot see through plasterboard — that is
physics — but you do not need to see through it if you scanned the wall
before it was closed up.

At first fix every pipe, cable, junction box and waste run is exposed. Scan
then and the position is recorded permanently. Board it, plaster it, paint
it; the record stands. Register the closed scan against the open one and the
services can be drawn back onto the finished wall at real coordinates.

Nothing open source does this. The research found IFC can REPRESENT MEP
systems (ifcopenshell.api.system) but nothing infers topology from a point
cloud — it is greenfield, which is exactly why it is defensible.

This module does the first half: given an open-scan cloud and the wall plane
it sits in, find the runs, size them against real UK product dimensions, and
check them against BS 7671 safe zones. Pairing with the closed scan is
register mode; drawing it on the wall is the app.

TWO THINGS IT REFUSES TO DO. It will not report a run it cannot size, and it
will never present an inferred service as a measured one. A builder drilling
into a wall on the strength of this needs to know which is which.
"""
import math
import os

# --- what UK first fix actually contains -----------------------------------
#
# Sizes are outside diameters in metres. Copper tube is BS EN 1057, plastic
# waste and soil are the common UK sizes, and twin-and-earth is measured
# across the flat because that is the dimension a scan sees.
#
# Tolerance is deliberately tight. The point of sizing a run is to tell 15mm
# from 22mm — get that wrong and the materials list is wrong — so a diameter
# that falls between two products is reported as unsized rather than snapped
# to the nearest.
SERVICES = (
    ("copper_10", 0.010, 0.0015, "10mm copper — microbore heating"),
    ("copper_15", 0.015, 0.0020, "15mm copper — taps, rads, most of a house"),
    ("copper_22", 0.022, 0.0025, "22mm copper — primary heating, bath feed"),
    ("copper_28", 0.028, 0.0030, "28mm copper — boiler primary, main runs"),
    ("waste_32", 0.032, 0.0030, "32mm waste — basin"),
    ("waste_40", 0.040, 0.0035, "40mm waste — sink, bath, shower"),
    ("waste_50", 0.050, 0.0040, "50mm waste — combined runs"),
    ("soil_110", 0.110, 0.0060, "110mm soil — WC and stack"),
    ("conduit_20", 0.020, 0.0020, "20mm conduit — cables in a chase"),
    ("conduit_25", 0.025, 0.0025, "25mm conduit"),
)

# Twin-and-earth is flat, not round, so it is matched on its wider dimension
# and never confused with a pipe.
CABLE_FLAT = (
    ("twin_earth_1.5", 0.0085, 0.0015, "1.5mm2 T&E — lighting"),
    ("twin_earth_2.5", 0.0100, 0.0015, "2.5mm2 T&E — sockets"),
    ("twin_earth_6.0", 0.0135, 0.0020, "6mm2 T&E — shower, cooker"),
)

# --- BS 7671 safe zones ----------------------------------------------------
#
# Regulation 522.6.202/203. A cable concealed in a wall at less than 50mm
# depth must either run in a permitted zone, or have earthed mechanical
# protection, or be RCD protected. The zones are:
#
#   * within 150mm of the top of the wall
#   * within 150mm of an angle formed by two adjoining walls
#   * horizontally or vertically in line with an accessory (socket, switch)
#
# A run outside those zones is where somebody puts a shelf bracket through a
# live cable. Finding one is worth more than any quantity this module
# produces, so it is reported as a hazard rather than a note.
SAFE_ZONE_M = 0.150

# Depth below which BS 7671 requires additional protection.
SHALLOW_DEPTH_M = 0.050

# A run shorter than this is a fitting, a bend or noise — not a run.
MIN_RUN_LENGTH_M = 0.20

# Points closer than this to the wall plane are the wall itself, not services.
WALL_SURFACE_TOLERANCE_M = 0.012

# Typical UK stud depth. Anything deeper than this behind the plane is
# another room, not this wall's void.
MAX_VOID_DEPTH_M = 0.20

# How many empty cells a run may jump before it is treated as two runs.
# Services are occluded constantly — a pipe passes behind a stud, a clip, a
# noggin — and without this a single continuous run comes back chopped into
# fragments, each too short to survive the length filter. Three cells is
# ~60mm, which bridges a 45mm stud and nothing larger.
MAX_GAP_CELLS = 3

# The widest thing that is still one run. A 110mm soil pipe is the largest
# service in a domestic wall; a 160mm drain does not go in one. Beyond this,
# parallel lines of cells are two runs side by side, not one fat one.
MAX_RUN_WIDTH_M = 0.130

# Resolution the cross-section profile is measured at. Much finer than the
# tracing grid, because a 10mm cable and a 15mm pipe both fit inside one
# 20mm cell and nothing about their shape survives at that scale.
PROFILE_BIN_M = 0.001


class ServicesError(ValueError):
    """Raised when services cannot be recovered honestly.

    A builder may drill on the strength of this. Guessing is not an option
    available to this module.
    """


# --- geometry --------------------------------------------------------------

def point_to_plane(point, plane):
    """Signed distance from a point to a plane (a, b, c, d), normal unit."""
    a, b, c, d = plane
    return a * point[0] + b * point[1] + c * point[2] + d


def void_points(points, plane, max_depth=MAX_VOID_DEPTH_M,
                surface_tolerance=WALL_SURFACE_TOLERANCE_M):
    """Points sitting in the wall void rather than on its surface.

    At first fix the scanner sees the studs, the services between them, and
    whatever is beyond. Services are the things standing off the plane by
    more than the surface tolerance and less than the stud depth.
    """
    out = []
    for p in points:
        depth = point_to_plane(p, plane)
        if surface_tolerance < abs(depth) <= max_depth:
            out.append((p, abs(depth)))
    return out


def plane_basis(plane):
    """Two orthogonal in-plane axes for a wall, u across and v up.

    v is chosen to point up the wall wherever the wall is not itself
    horizontal, so "150mm from the top" means what a person means by it.
    """
    a, b, c, _d = plane
    normal = (a, b, c)
    up = (0.0, 0.0, 1.0)
    if abs(c) > 0.9:                       # a floor or ceiling, not a wall
        up = (0.0, 1.0, 0.0)
    # u RUNS WITH THE WALL, NOT AGAINST IT. cross(up, normal) returns the
    # negation of the wall's own direction for the normal structure emits
    # (nx, ny = -uy, ux), so a cable 2m along a wall measured u = -2.0m and
    # in_safe_zone's bounds gate refused it as "outside the wall — no zone
    # judgement is possible". Every run on every structure-traced wall, so
    # the X-ray could not judge a single BS 7671 zone: a shallow cable in a
    # prohibited zone came back unjudged rather than dangerous. Verified by
    # execution against a wall traced (0,0)->(5,0), not by reading.
    u = _normalise(_cross(normal, up))
    v = _normalise(_cross(u, normal))
    return u, v


def _cross(p, q):
    return (p[1] * q[2] - p[2] * q[1],
            p[2] * q[0] - p[0] * q[2],
            p[0] * q[1] - p[1] * q[0])


def _normalise(v):
    length = math.sqrt(sum(component * component for component in v))
    if length <= 0:
        raise ServicesError("degenerate wall plane — its normal has no length")
    return tuple(component / length for component in v)


def project_to_plane(points, plane, origin=None):
    """Wall-local (u, v) coordinates for a set of points.

    ORIGIN IS SUBTRACTED FIRST, and without it these are not wall-local
    coordinates at all — they are raw world projections wearing the name.
    On a wall running from (3,5) to (7,8), a pipe 1.000m along it was
    reported at u=6.380: off the end of a 5m wall, with nothing to say so.
    A builder cannot find a pipe from that, and in_safe_zone cannot judge
    one. On a building surveyed against the OS grid, u came back as 458210.

    origin is the wall's bottom-left corner in world space. Structure mode
    emits it as `origin` on every traced wall.
    """
    u, v = plane_basis(plane)
    ox, oy, oz = origin or (0.0, 0.0, 0.0)
    out = []
    for p in points:
        dx, dy, dz = p[0] - ox, p[1] - oy, p[2] - oz
        out.append((dx * u[0] + dy * u[1] + dz * u[2],
                    dx * v[0] + dy * v[1] + dz * v[2]))
    return out


# --- finding runs ----------------------------------------------------------

def trace_runs(void, plane, cell_m=0.02, min_length=MIN_RUN_LENGTH_M,
               max_gap_cells=MAX_GAP_CELLS, origin=None):
    """Group void points into straight service runs.

    Services at first fix are overwhelmingly vertical drops and horizontal
    legs — they are clipped to studs and noggins, and a plumber runs them
    square because that is what fits between the timbers. So the same
    axis-aligned tracing structure Structure Mode uses works here, and the
    same limitation applies: a diagonal run comes back as steps.

    PARALLEL LINES ARE MERGED, and this is what makes the module work at
    all. Tracing one line of cells at a time meant a run wider than a cell
    became several runs side by side: a single 110mm soil pipe came back as
    three, totalling 6.06m for a 2.00m pipe. Worse, no single line can show
    a run's WIDTH, so width_m was never emitted, so profile_of() — the
    round/flat test this module calls THE discriminator between a pipe and a
    cable — always returned None. identify() was never confident, is_cable
    was never set, and totals.compliance_failures was structurally always
    zero. The BS 7671 check could not fire. A module whose stated purpose is
    finding a cable before someone drills into it could not report one.
    """
    if not void:
        return []

    points = [p for p, _depth in void]
    cells = {}
    flat = project_to_plane(points, plane, origin)
    for (u, v), (_p, depth) in zip(flat, void):
        key = (int(math.floor(u / cell_m)), int(math.floor(v / cell_m)))
        seen = cells.get(key)
        if seen is None:
            seen = cells[key] = {"d_min": depth, "d_max": depth, "n": 1,
                                 "u_min": u, "u_max": u,
                                 "v_min": v, "v_max": v,
                                 "prof_u": {}, "prof_v": {}}
        else:
            seen["d_min"] = min(seen["d_min"], depth)
            seen["d_max"] = max(seen["d_max"], depth)
            seen["u_min"] = min(seen["u_min"], u)
            seen["u_max"] = max(seen["u_max"], u)
            seen["v_min"] = min(seen["v_min"], v)
            seen["v_max"] = max(seen["v_max"], v)
            seen["n"] += 1
        # The cross-section, at a much finer resolution than the tracing
        # grid: a 10mm cable and a 15mm pipe both fit inside one 20mm cell,
        # so nothing about their shape survives at cell resolution.
        for name, coord in (("prof_u", u), ("prof_v", v)):
            bin_key = int(math.floor(coord / PROFILE_BIN_M))
            band = seen[name]
            if depth > band.get(bin_key, -1.0):
                band[bin_key] = depth

    runs = []
    for axis in (0, 1):
        lines = {}
        for (cu, cv) in cells:
            key = cv if axis == 0 else cu
            lines.setdefault(key, []).append(cu if axis == 0 else cv)

        segments = []
        for key, along in lines.items():
            along.sort()
            start = previous = along[0]
            for value in along[1:] + [None]:
                if value is not None and value - previous <= max_gap_cells:
                    previous = value
                    continue
                segments.append((key, start, previous))
                if value is None:
                    break
                start = previous = value

        runs.extend(_merge_lines(axis, segments, cells, cell_m, min_length))

    return sorted(runs, key=lambda r: -r["length_m"])


def _merge_lines(axis, segments, cells, cell_m, min_length):
    """Collapse the parallel cell lines through one run into a single run."""
    # Same rule as structure.trace_walls: near lines whose extents
    # substantially COINCIDE are the same run. Overlap alone would chain a
    # crossing run into this one at the point they meet.
    window = max(1, int(round(MAX_RUN_WIDTH_M / cell_m)))
    segments.sort(key=lambda s: (s[0], s[1]))
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (ki, lo_i, hi_i) in enumerate(segments):
        span_i = hi_i - lo_i + 1
        for j in range(i + 1, len(segments)):
            kj, lo_j, hi_j = segments[j]
            if kj - ki > window:
                break
            if kj == ki:
                continue
            overlap = min(hi_i, hi_j) - max(lo_i, lo_j) + 1
            if overlap >= 0.8 * max(span_i, hi_j - lo_j + 1):
                parent[find(j)] = find(i)

    clusters = {}
    for i in range(len(segments)):
        clusters.setdefault(find(i), []).append(segments[i])

    out = []
    for members in clusters.values():
        keys = [
            (index, key) if axis == 0 else (key, index)
            for key, lo, hi in members for index in range(lo, hi + 1)
        ]
        keys = [k for k in keys if k in cells]
        if not keys:
            continue
        records = [cells[k] for k in keys]

        u_lo = min(r["u_min"] for r in records)
        u_hi = max(r["u_max"] for r in records)
        v_lo = min(r["v_min"] for r in records)
        v_hi = max(r["v_max"] for r in records)
        along = (u_hi - u_lo) if axis == 0 else (v_hi - v_lo)
        across = (v_hi - v_lo) if axis == 0 else (u_hi - u_lo)
        if along < min_length:
            continue
        # Wider than it is long is the perpendicular run seen end-on; the
        # other axis traces it properly.
        if across > min(MAX_RUN_WIDTH_M, along):
            continue

        band = "prof_v" if axis == 0 else "prof_u"
        merged = {}
        for record in records:
            for bin_key, depth in record[band].items():
                if depth > merged.get(bin_key, -1.0):
                    merged[bin_key] = depth

        out.append({
            "axis": "horizontal" if axis == 0 else "vertical",
            "length_m": round(along, 3),
            "width_m": round(across, 4),
            "u_m": round(u_lo, 3),
            "v_m": round(v_lo, 3),
            "u_end_m": round(u_hi, 3),
            "v_end_m": round(v_hi, 3),
            "depth_m": round(sum(r["d_min"] for r in records)
                             / len(records), 4),
            "thickness_m": round(_thickness(records), 4),
            "flat_share": _flat_share(merged),
            "points": sum(r["n"] for r in records),
        })
    return out


def _flat_share(profile):
    """How much of a run's width stands at close to its full depth.

    This is the round/flat discriminator, and it replaces a ratio of two
    extents that could not work. A scanner in the room sees the face of a
    service that is turned towards it, so for a pipe it sees the near HALF
    of a cylinder: the depth spread it measures is the RADIUS, not the
    diameter. 10mm copper therefore measured 10mm across and 5mm deep, a
    ratio of 2.0 — squarely in the "flat" band — and was reported as
    2.5mm2 twin-and-earth. A pipe identified as a cable is the same error
    as a cable identified as a pipe, and it is the error this module exists
    to prevent.

    What actually separates them is the SHAPE of the cross-section. A cable
    presents a flat face: near enough constant depth right across its width,
    then a sharp edge. A pipe is a curve, deepest along its crown and
    falling away continuously to either side. Measuring the share of the
    width sitting within 15% of the peak gives ~1.0 for a flat face and
    ~0.53 for a circle, which is a wide enough gap to judge on.

    Measured relative to the run's OWN shallowest point, not to the wall.
    A service sits on a clip or a batten, and that standoff — 20mm is
    typical — is shared by every part of the cross-section. Left in, it
    swamps the few millimetres of shape: a 10mm pipe standing 20mm off the
    wall varies between 25mm and 30mm deep, which is within 15% right across
    its width, so a circle measured as flat and copper came back as cable.

    Returns None when the run is too narrow to resolve a shape at all.
    """
    if len(profile) < 4:
        return None
    peak = max(profile.values())
    floor = min(profile.values())
    relief = peak - floor
    if relief <= 0:
        # Constant depth right across the run. That IS a flat face — it is
        # what a cable looks like — and reporting it as unknown threw away
        # the cleanest reading the method produces.
        return 1.0
    near = sum(1 for d in profile.values() if d - floor >= relief * 0.85)
    return round(near / len(profile), 3)


def _thickness(records):
    """Apparent cross-section of a run, from how far it stands off the plane.

    A scanner sees the near face of a pipe, so the depth spread across the
    run's cells approximates its diameter. Approximate is the honest word:
    it is why identify() refuses rather than rounds when the number falls
    between two products.

    NO FLOOR. The first version floored this at half a cell — 10.0mm at the
    default 20mm cell — which is exactly the one collision in the product
    table: 10mm microbore copper against 2.5mm2 twin-and-earth. Every run in
    the worker reported a thickness of precisely 10.0mm, so nothing was ever
    identifiable. A thin measurement is now reported as thin, and identify()
    refuses it if it matches nothing, which is the honest answer.
    """
    if not records:
        return 0.0
    return max(r["d_max"] for r in records) - min(r["d_min"] for r in records)


# --- what is it? -----------------------------------------------------------

def profile_of(run):
    """Whether a run's cross-section is round or flat. None if unknown.

    THE discriminator between a pipe and a cable, and it is not size. 10mm
    microbore copper and 2.5mm2 twin-and-earth are both nominally 10mm
    across, so no measurement of one dimension can separate them.

    It is not the ratio of two dimensions either, which is what this used to
    be. See _flat_share: a scanner sees half a cylinder, so a pipe's
    measured depth is its radius and its width-to-depth ratio is about 2 —
    the same as a cable's. Both read as "flat" and copper was reported as
    cable. It is the SHAPE of the cross-section that separates them.
    """
    share = run.get("flat_share") if isinstance(run, dict) else None
    if share is None:
        return None
    if share >= 0.80:
        return "flat"
    if share <= 0.65:
        return "round"
    return None


def characteristic_size(run):
    """The dimension a product is actually NAMED by, and its profile.

    For both families that is the width the scan sees ACROSS the run — the
    silhouette. For a pipe that width is its diameter, which is what it is
    called. For twin and earth it is the ~10mm across the flat, which is the
    only dimension of a 2.5mm2 cable a scan can see; matching it on its ~4mm
    thickness looks for a 4mm product, and there isn't one.

    Returning the DEPTH for round goods, as this used to, asked for a 7.5mm
    product when looking at 15mm copper — half the true size, every time.
    """
    if not isinstance(run, dict):
        return None, None
    return run.get("width_m"), profile_of(run)


def identify(size_m, profile=None):
    """Match a measured cross-section to a real UK product.

    `size_m` is the dimension the product is named by — a diameter for round
    goods, the width across the flat for cable. See characteristic_size().

    Refuses when the measurement falls between two products rather than
    snapping to the nearest. 15mm and 22mm copper are 7mm apart; a scan
    that cannot tell them apart must say so, because the difference is a
    wrong materials list and a wrong price.

    `profile` — "round" or "flat" from profile_of() — resolves the one
    genuine collision in the table, 10mm copper against 2.5mm2 T&E.
    """
    if size_m is None or size_m <= 0:
        return None

    candidates = list(SERVICES) + list(CABLE_FLAT)
    if profile == "round":
        candidates = list(SERVICES)
    elif profile == "flat":
        candidates = list(CABLE_FLAT)

    matches = []
    for key, size, tolerance, label in candidates:
        if abs(size_m - size) <= tolerance:
            matches.append((abs(size_m - size), key, size, label))

    if not matches:
        return {
            "type": None,
            "measured_mm": round(size_m * 1000, 1),
            "confident": False,
            "note": (f"{size_m * 1000:.0f}mm does not match a standard UK "
                     f"pipe, conduit or cable. Verify on site before "
                     f"drilling."),
        }
    matches.sort()
    if len(matches) > 1 and matches[1][0] - matches[0][0] < 0.0008:
        return {
            "type": None,
            "measured_mm": round(size_m * 1000, 1),
            "candidates": [m[1] for m in matches[:2]],
            "confident": False,
            "note": (f"{size_m * 1000:.0f}mm sits between "
                     f"{matches[0][1]} and {matches[1][1]}. The scan cannot "
                     f"tell them apart. If the run's second dimension was "
                     f"captured, pass width_m so the round/flat profile can "
                     f"separate them; otherwise measure it before ordering."),
        }

    _delta, key, size, label = matches[0]
    return {
        "type": key,
        "nominal_mm": round(size * 1000, 1),
        "measured_mm": round(size_m * 1000, 1),
        "confident": True,
        "description": label,
        "is_cable": key.startswith("twin_earth"),
    }


# --- BS 7671 safe zones ----------------------------------------------------

def in_safe_zone(run, wall, accessories=None):
    """Whether a cable run sits in a BS 7671 permitted zone.

    Regulation 522.6.202/203: within 150mm of the top of the wall, within
    150mm of an angle with an adjoining wall, or in line horizontally or
    vertically with an accessory.

    Only meaningful for cables. A pipe outside a "safe zone" is not a
    regulatory problem — it is just a pipe — and reporting it as one would
    bury the cable findings that matter.

    TWO FAILURES, BOTH TOWARD "SAFE", both fixed here.

    The tests were one-sided. `height - v <= SAFE_ZONE_M` is satisfied by
    every v ABOVE the wall as well as every v near its top, and `width - u`
    likewise, so any run whose coordinates fell outside the wall's nominal
    range read as compliant. Only a ground-floor wall with its corner exactly
    at the world origin was assessed correctly; move the same room 6m along,
    or up one storey, or survey it against the OS grid, and a dangerous
    cable flipped to PASS. (The coordinates themselves were the deeper
    fault — see project_to_plane.)

    A run was also treated as its single start corner, with length_m and
    axis ignored. A cable straight across the middle of a wall passed
    because its left end touched a corner, while 3.7m of it sat in no zone
    at all. The whole EXTENT is now tested, and a run only counts as in a
    zone if all of it is: BS 7671 protects the cable, not its endpoint.
    """
    width = wall.get("width_m")
    height = wall.get("height_m")
    if not width or not height:
        raise ServicesError(
            "safe zones need the wall's width and height — the zones are "
            "defined relative to its edges")

    u0, v0 = run["u_m"], run["v_m"]
    u1 = run.get("u_end_m", u0)
    v1 = run.get("v_end_m", v0)
    if run.get("length_m") and "u_end_m" not in run:
        # A run recorded only by its start corner: derive the far end.
        if run.get("axis") == "horizontal":
            u1 = u0 + run["length_m"]
        else:
            v1 = v0 + run["length_m"]
    u0, u1 = min(u0, u1), max(u0, u1)
    v0, v1 = min(v0, v1), max(v0, v1)

    reasons = []
    if not (-SAFE_ZONE_M <= u0 and u1 <= width + SAFE_ZONE_M
            and -SAFE_ZONE_M <= v0 and v1 <= height + SAFE_ZONE_M):
        return {
            "in_zone": False,
            "reasons": [],
            "note": (f"this run lies outside the wall it was measured "
                     f"against (u {u0:.2f}–{u1:.2f}m on a {width:.2f}m wall, "
                     f"v {v0:.2f}–{v1:.2f}m on a {height:.2f}m wall). No "
                     f"zone judgement is possible — check the wall origin."),
        }

    # Every part of the run must be in the zone, so test the far edge.
    if height - v0 <= SAFE_ZONE_M:
        reasons.append("within 150mm of the top of the wall")
    if u1 <= SAFE_ZONE_M or width - u0 <= SAFE_ZONE_M:
        reasons.append("within 150mm of a wall angle")

    for accessory in (accessories or []):
        au = accessory.get("u_m")
        if au is not None and u0 - SAFE_ZONE_M <= au <= u1 + SAFE_ZONE_M:
            reasons.append(
                f"vertically in line with {accessory.get('name', 'an accessory')}")
        av = accessory.get("v_m")
        if av is not None and v0 - SAFE_ZONE_M <= av <= v1 + SAFE_ZONE_M:
            reasons.append(
                f"horizontally in line with {accessory.get('name', 'an accessory')}")

    return {"in_zone": bool(reasons), "reasons": reasons}


def check_run(run, wall, accessories=None):
    """Full assessment of one run: what it is, and whether it is compliant."""
    identity = identify(*characteristic_size(run))
    assessment = {"run": run, "identity": identity}

    if not identity or not identity.get("is_cable"):
        assessment["compliance"] = None
        return assessment

    zone = in_safe_zone(run, wall, accessories)
    shallow = run.get("depth_m", 1.0) < SHALLOW_DEPTH_M
    assessment["safe_zone"] = zone

    if zone["in_zone"]:
        assessment["compliance"] = {
            "verdict": "PASS",
            "note": "Cable runs in a BS 7671 permitted zone (" +
                    "; ".join(zone["reasons"]) + ").",
        }
    elif not shallow:
        assessment["compliance"] = {
            "verdict": "PASS",
            "note": (f"Cable is {run['depth_m'] * 1000:.0f}mm deep, beyond the "
                     f"50mm at which BS 7671 522.6.202 applies."),
        }
    else:
        assessment["compliance"] = {
            "verdict": "FAIL",
            "severity": "critical",
            "note": (f"Cable runs outside every permitted zone at only "
                     f"{run['depth_m'] * 1000:.0f}mm deep. BS 7671 522.6.202 "
                     f"requires earthed mechanical protection or RCD "
                     f"protection here. This is where a shelf bracket goes "
                     f"through a live cable."),
        }
    return assessment


# --- the whole thing -------------------------------------------------------

def extract(points, wall, accessories=None):
    """Open-scan cloud plus a wall definition, in; services out."""
    plane = wall.get("plane")
    if not plane or len(plane) != 4:
        raise ServicesError(
            "services mode needs the wall plane as (a, b, c, d) with a unit "
            "normal. Structure mode emits it on every traced wall, as "
            "`plane`, alongside `origin`, `width_m` and `height_m`.")
    if not wall.get("width_m") or not wall.get("height_m"):
        raise ServicesError(
            "services mode needs the wall's width_m and height_m as well as "
            "its plane — the BS 7671 safe zones are defined relative to its "
            "edges, and without them no cable can be assessed.")
    if not points:
        raise ServicesError("no points supplied")

    origin = wall.get("origin")
    if origin is None:
        # Without it, (u, v) are world projections and every distance to a
        # wall edge is measured from the wrong place. Answer honestly rather
        # than assessing against coordinates that do not mean what they say.
        raise ServicesError(
            "services mode needs the wall's `origin` — its bottom-left "
            "corner in world coordinates. Without it a run's position on "
            "the wall cannot be established, so neither can its BS 7671 "
            "zone. Structure mode emits it on every traced wall.")

    void = void_points(points, plane)
    if not void:
        return {
            "runs": [], "totals": {"runs": 0},
            "warnings": [
                "No points stand off the wall plane, so there is nothing in "
                "this void to record. Either the wall was already boarded "
                "when it was scanned, or the plane is wrong."],
        }

    runs = trace_runs(void, plane, origin=origin)
    assessed = [check_run(r, wall, accessories) for r in runs]

    cables = [a for a in assessed
              if a["identity"] and a["identity"].get("is_cable")]
    unsized = [a for a in assessed
               if not a["identity"] or not a["identity"]["confident"]]
    failures = [a for a in assessed
                if (a.get("compliance") or {}).get("verdict") == "FAIL"]

    warnings = []
    if unsized:
        warnings.append(
            f"{len(unsized)} of {len(assessed)} runs could not be sized "
            f"confidently. They are recorded with their measured dimension "
            f"and must be verified before ordering or drilling.")
    if failures:
        warnings.append(
            f"{len(failures)} cable run(s) sit outside every BS 7671 "
            f"permitted zone at less than 50mm depth. That is a safety "
            f"finding, not a measurement one — see the compliance verdicts.")
    warnings.append(
        "Runs are traced axis-aligned, so diagonal drops come back as steps.")
    warnings.append(
        "This is a record of what was EXPOSED when the scan was taken. "
        "Anything installed after it is not here.")

    return {
        "runs": assessed,
        "totals": {
            "runs": len(assessed),
            "cables": len(cables),
            "pipes": len(assessed) - len(cables),
            "unsized": len(unsized),
            "compliance_failures": len(failures),
            "length_m": round(sum(r["length_m"] for r in runs), 2),
        },
        "basis": ("Measured from an open scan taken before boarding. Every "
                  "run here was physically visible to the scanner — none of "
                  "it is inferred."),
        "warnings": warnings,
    }


# --- handler entry point ---------------------------------------------------

def run(spec, prog, output_dir):
    """Services mode entry point."""
    import json
    import paths
    import structure

    prog.stage("fetching")
    cloud = spec.get("point_cloud_path") or spec.get("point_cloud_url")
    if not cloud:
        raise ServicesError(
            "services mode needs an open-scan point cloud — one taken at "
            "first fix, before the plasterboard went on.")
    wall = spec.get("wall")
    if not wall:
        raise ServicesError(
            "services mode needs the wall to look in: {plane: [a,b,c,d], "
            "width_m, height_m}. Structure mode produces the plane.")

    if spec.get("stage") == "closed":
        raise ServicesError(
            "this is marked as a closed scan. Services can only be recovered "
            "from an OPEN scan, taken before boarding — that is the whole "
            "idea. Use register mode to pair a closed scan against one.")

    if not os.path.exists(cloud):
        import validation
        local = os.path.join(paths.ensure(output_dir), "open.ply")
        response = validation.fetch_checked(cloud, "point_cloud_url",
                                            timeout=600)
        response.raise_for_status()
        with open(local, "wb") as f:
            f.write(response.content)
        cloud = local

    points = structure.read_ply(cloud)

    prog.stage("extracting_runs")
    result = extract(points, wall, spec.get("accessories"))

    prog.stage("classifying")
    prog.stage("exporting")
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "services"
    path = os.path.join(directory, f"{scan}.services.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    return ([(path, f"services/{scan}.json", None)],
            {"services": result, "warnings": result["warnings"]})
