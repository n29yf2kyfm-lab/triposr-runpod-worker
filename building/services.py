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
    u = _cross(up, normal)
    u = _normalise(u)
    v = _normalise(_cross(normal, u))
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


def project_to_plane(points, plane):
    """Wall-local (u, v) coordinates for a set of points."""
    u, v = plane_basis(plane)
    return [((p[0] * u[0] + p[1] * u[1] + p[2] * u[2]),
             (p[0] * v[0] + p[1] * v[1] + p[2] * v[2])) for p in points]


# --- finding runs ----------------------------------------------------------

def trace_runs(void, plane, cell_m=0.02, min_length=MIN_RUN_LENGTH_M,
               max_gap_cells=MAX_GAP_CELLS):
    """Group void points into straight service runs.

    Services at first fix are overwhelmingly vertical drops and horizontal
    legs — they are clipped to studs and noggins, and a plumber runs them
    square because that is what fits between the timbers. So the same
    axis-aligned tracing structure Structure Mode uses works here, and the
    same limitation applies: a diagonal run comes back as steps.
    """
    if not void:
        return []

    points = [p for p, _depth in void]
    depths = {}
    flat = project_to_plane(points, plane)
    for (u, v), (_p, depth) in zip(flat, void):
        key = (int(math.floor(u / cell_m)), int(math.floor(v / cell_m)))
        seen = depths.get(key)
        if seen is None:
            depths[key] = [depth, depth, 1]
        else:
            seen[0] = min(seen[0], depth)
            seen[1] = max(seen[1], depth)
            seen[2] += 1

    runs = []
    for axis in (0, 1):
        lines = {}
        for (cu, cv) in depths:
            key = cv if axis == 0 else cu
            lines.setdefault(key, []).append(cu if axis == 0 else cv)

        for key, along in lines.items():
            along.sort()
            start = previous = along[0]
            for value in along[1:] + [None]:
                if value is not None and value - previous <= max_gap_cells:
                    previous = value
                    continue
                length = (previous - start + 1) * cell_m
                if length >= min_length:
                    members = [(key, i) if axis else (i, key)
                               for i in range(start, previous + 1)]
                    members = [m for m in members if m in depths]
                    thickness = _thickness(members, depths, cell_m)
                    runs.append({
                        "axis": "horizontal" if axis == 0 else "vertical",
                        "length_m": round(length, 3),
                        "u_m": round((start if axis == 0 else key) * cell_m, 3),
                        "v_m": round((key if axis == 0 else start) * cell_m, 3),
                        "depth_m": round(
                            sum(depths[m][0] for m in members) / len(members), 4),
                        "thickness_m": round(thickness, 4),
                        "points": sum(depths[m][2] for m in members),
                    })
                if value is None:
                    break
                start = previous = value
    return sorted(runs, key=lambda r: -r["length_m"])


def _thickness(members, depths, cell_m):
    """Apparent cross-section of a run, from how far it stands off the plane.

    A scanner sees the near face of a pipe, so the depth spread across the
    run's cells approximates its diameter. Approximate is the honest word:
    it is why identify() refuses rather than rounds when the number falls
    between two products.
    """
    if not members:
        return 0.0
    spread = max(depths[m][1] for m in members) - min(depths[m][0]
                                                      for m in members)
    # A single-cell-wide run cannot show its diameter through depth spread
    # alone, so fall back to the cell size as a floor.
    return max(spread, cell_m * 0.5)


# --- what is it? -----------------------------------------------------------

def profile_of(thickness_m, width_m):
    """Whether a run's cross-section is round or flat. None if unknown.

    THE discriminator between a pipe and a cable, and it is not size. 10mm
    microbore copper and 2.5mm2 twin-and-earth are both nominally 10mm
    across, so no measurement of one dimension can separate them — but
    copper is round and T&E is flat, roughly 10mm by 4mm. A scan that
    captures both dimensions of a run knows which it is; one that captures
    only the diameter genuinely does not, and says so.
    """
    if not thickness_m or not width_m or thickness_m <= 0 or width_m <= 0:
        return None
    ratio = max(width_m, thickness_m) / min(width_m, thickness_m)
    if ratio >= 1.8:
        return "flat"
    if ratio <= 1.3:
        return "round"
    return None


def characteristic_size(run):
    """The dimension a product is actually NAMED by, and its profile.

    Round and flat products are named by different things, and mixing them up
    finds nothing. A pipe is called 15mm because that is its diameter. Twin
    and earth is called 2.5mm2, but the dimension a scan can see is its ~10mm
    width ACROSS THE FLAT — not its ~4mm thickness. Matching a flat cable on
    its thin dimension looks for a 4mm product, and there isn't one.
    """
    thickness = run.get("thickness_m")
    width = run.get("width_m")
    profile = profile_of(thickness, width)
    if profile == "flat":
        return max(thickness or 0.0, width or 0.0), profile
    return thickness, profile


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
    """
    width = wall.get("width_m")
    height = wall.get("height_m")
    if not width or not height:
        raise ServicesError(
            "safe zones need the wall's width and height — the zones are "
            "defined relative to its edges")

    u, v = run["u_m"], run["v_m"]
    reasons = []

    if height - v <= SAFE_ZONE_M:
        reasons.append("within 150mm of the top of the wall")
    if u <= SAFE_ZONE_M or width - u <= SAFE_ZONE_M:
        reasons.append("within 150mm of a wall angle")

    for accessory in (accessories or []):
        if abs(accessory.get("u_m", 1e9) - u) <= SAFE_ZONE_M:
            reasons.append(
                f"vertically in line with {accessory.get('name', 'an accessory')}")
        if abs(accessory.get("v_m", 1e9) - v) <= SAFE_ZONE_M:
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
            "normal — structure mode produces it.")
    if not wall.get("width_m") or not wall.get("height_m"):
        raise ServicesError(
            "services mode needs the wall's width_m and height_m as well as "
            "its plane — the BS 7671 safe zones are defined relative to its "
            "edges, and without them no cable can be assessed.")
    if not points:
        raise ServicesError("no points supplied")

    void = void_points(points, plane)
    if not void:
        return {
            "runs": [], "totals": {"runs": 0},
            "warnings": [
                "No points stand off the wall plane, so there is nothing in "
                "this void to record. Either the wall was already boarded "
                "when it was scanned, or the plane is wrong."],
        }

    runs = trace_runs(void, plane)
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
        validation.check_fetchable_url(cloud, "point_cloud_url")
        import requests
        local = os.path.join(paths.ensure(output_dir), "open.ply")
        response = requests.get(cloud, timeout=600)
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
