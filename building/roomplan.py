"""Apple RoomPlan ingest — a scanned room into the same model everything
else uses.

RoomPlan (iOS 16+, iPhone/iPad Pro with LiDAR) hands back a PARAMETRIC room:
walls, doors, windows and openings as labelled objects with real metric
dimensions, not a mesh to be reverse-engineered. That makes it the highest
value capture input this worker can receive — the segmentation problem that
Phase 3 exists to solve arrives already solved, done on the phone.

This module reads the JSON export of a CapturedRoom (the Swift type is
Codable; Apple's own sample scanner app and the common third-party scanners
all write it) and produces the same model dict that model3d.build() produces
from a drawing's figured dimensions, so every existing export — OBJ, GLB,
IFC, take-off JSON — works on a scan without knowing where it came from.

GEOMETRY, and the two traps in it:

* Transforms are 4x4 column-major in ARKit world space, Y up. A wall's
  centre is the translation column; its run direction is the local X axis
  taken through the rotation. The plan here is (world x, -world z) — looking
  down with Y toward the viewer — so lengths and areas survive untouched.

* The scan's axes are wherever the phone happened to be pointing when the
  session started. Every wall arrives rotated by that arbitrary yaw, so the
  plan is de-rotated by the dominant wall direction (length-weighted, mod
  90 degrees) before anything else looks at it. Walls within SNAP_DEG of an
  axis after that are snapped — that residue is LiDAR noise, not
  architecture. Walls genuinely off-axis stay at their true angle: the GLB
  and IFC writers handle any angle exactly; write_obj boxes walls along an
  axis, so those walls are flagged in a warning rather than silently drawn
  as a different building.
"""
import json
import math
import os

from model3d import Wall, ModelError

# Snap tolerance for near-axis walls after de-rotation. Half a degree of
# yaw over a 4m wall is 35mm of drift at the far end — well inside RoomPlan's
# own error — while a genuine 10-degree splay is architecture and stays.
SNAP_DEG = 5.0

# An opening must sit within this of its wall's centreline to be attached by
# proximity when the export carries no parentIdentifier. Generous because the
# opening's transform is at the leaf/pane, not the wall core.
ATTACH_M = 0.5

# Sanity bounds. A wall dimension outside these is a unit or schema error,
# not a building — the same reasoning as validation's 0.3–200m room bounds.
MIN_WALL_M = 0.1
MAX_WALL_M = 200.0

DEFAULT_WALL_HEIGHT_M = 2.4
SCAN_WALL_THICKNESS_M = 0.1


class RoomPlanError(ModelError):
    """The export could not be read as a RoomPlan capture."""


# --- schema reading ---------------------------------------------------------
#
# Tolerant on purpose. Apple's Codable encoding writes enum categories as
# {"wall": {}}; some exporters flatten that to the string "wall"; dimensions
# are a 3-list and transforms a 16-list, but at least one scanner nests the
# matrix as four rows. All of those are the same capture and all are read.


def _category(surface):
    cat = surface.get("category")
    if isinstance(cat, str):
        return cat.lower()
    if isinstance(cat, dict) and cat:
        return str(next(iter(cat.keys()))).lower()
    return ""


def _matrix(surface):
    m = surface.get("transform")
    if isinstance(m, list) and len(m) == 4 and all(
            isinstance(r, list) and len(r) == 4 for r in m):
        # Row-nested: assume column-major columns, as simd encodes.
        m = [v for col in m for v in col]
    if not (isinstance(m, list) and len(m) == 16):
        raise RoomPlanError(
            "a surface has no usable 4x4 transform — this does not look "
            "like a RoomPlan export")
    return [float(v) for v in m]


def _dimensions(surface):
    d = surface.get("dimensions")
    if not (isinstance(d, list) and len(d) >= 2):
        raise RoomPlanError(
            "a surface has no [width, height, ...] dimensions — this does "
            "not look like a RoomPlan export")
    return [float(v) for v in d]


def _plan_xy(m):
    """Plan position of a transform: (world x, -world z), Y-up discarded."""
    return m[12], -m[14]


def _plan_dir(m):
    """Plan direction of the local X axis (a wall's run)."""
    dx, dz = m[0], m[2]
    return dx, -dz


def _load(source):
    if isinstance(source, dict):
        return source
    text = None
    if isinstance(source, (str, os.PathLike)) and os.path.exists(source):
        with open(source, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    elif isinstance(source, str) and source.lstrip().startswith("{"):
        text = source
    else:
        raise RoomPlanError(f"roomplan source not found: {source}")
    try:
        return json.loads(text)
    except ValueError as e:
        raise RoomPlanError(f"roomplan export is not valid JSON: {e}")


# --- parsing ----------------------------------------------------------------


def parse(source):
    """A CapturedRoom JSON export into plan-space walls and openings.

    Returns a dict of {walls, openings, floors, rotation_deg, warnings}
    still in scan coordinates de-rotated to the dominant wall direction —
    to_model() below turns it into the model3d shape.
    """
    doc = _load(source)
    raw_walls = doc.get("walls")
    if not isinstance(raw_walls, list) or not raw_walls:
        raise RoomPlanError(
            "the export has no walls — RoomPlan writes a `walls` array even "
            "for a partial scan, so this is either not a RoomPlan export or "
            "the scan captured nothing")

    warnings = []
    walls = []
    for i, s in enumerate(raw_walls):
        m = _matrix(s)
        dims = _dimensions(s)
        length, height = dims[0], dims[1]
        if not (MIN_WALL_M <= length <= MAX_WALL_M
                and MIN_WALL_M <= height <= MAX_WALL_M):
            raise RoomPlanError(
                f"wall {i} is {length:.3f}m x {height:.3f}m — outside "
                f"anything a wall could be. RoomPlan writes metres; a value "
                f"like this means the export is not what it claims to be.")
        cx, cy = _plan_xy(m)
        dx, dy = _plan_dir(m)
        n = math.hypot(dx, dy)
        if n < 1e-9:
            # A wall lying flat in plan is not a wall.
            raise RoomPlanError(f"wall {i} has no run direction in plan")
        dx, dy = dx / n, dy / n
        walls.append({
            "id": s.get("identifier") or f"wall-{i}",
            "cx": cx, "cy": cy, "dx": dx, "dy": dy,
            "length": length, "height": height,
            "base": m[13] - height / 2.0,     # world Y of the wall's foot
        })

    # Dominant orientation: length-weighted circular mean of 4*theta, so a
    # direction and its perpendicular vote for the same answer. This is what
    # lets a scan started at any angle come out square.
    sc = ss = 0.0
    for w in walls:
        theta = math.atan2(w["dy"], w["dx"])
        sc += w["length"] * math.cos(4 * theta)
        ss += w["length"] * math.sin(4 * theta)
    rot = math.atan2(ss, sc) / 4.0 if (sc or ss) else 0.0
    cr, sr = math.cos(-rot), math.sin(-rot)

    def derot(x, y):
        return x * cr - y * sr, x * sr + y * cr

    snapped = off_axis = 0
    for w in walls:
        w["cx"], w["cy"] = derot(w["cx"], w["cy"])
        w["dx"], w["dy"] = derot(w["dx"], w["dy"])
        theta = math.degrees(math.atan2(w["dy"], w["dx"]))
        residue = min(abs(theta % 90), 90 - abs(theta % 90))
        if residue <= SNAP_DEG:
            if abs(w["dx"]) >= abs(w["dy"]):
                w["dx"], w["dy"] = (1.0 if w["dx"] >= 0 else -1.0), 0.0
            else:
                w["dx"], w["dy"] = 0.0, (1.0 if w["dy"] >= 0 else -1.0)
            if residue > 1e-9:
                snapped += 1
        else:
            off_axis += 1
            w["off_axis_deg"] = round(residue, 1)

    if math.degrees(abs(rot)) > 0.05:
        warnings.append(
            f"Scan de-rotated by {math.degrees(rot):.1f} degrees to square "
            f"the plan — RoomPlan's axes are wherever the phone pointed "
            f"first, not the building's.")
    if off_axis:
        warnings.append(
            f"{off_axis} wall(s) genuinely off-axis (splayed or angled) — "
            f"exact in the GLB, IFC, JSON and every quantity; the OBJ draws "
            f"walls axis-aligned, so open one of the others to see them at "
            f"their true angle.")

    # Endpoints, ordered ascending so both mesh writers measure an opening's
    # `along` from the same end (write_obj sorts; _glb_mesh does not).
    for w in walls:
        hx, hy = w["dx"] * w["length"] / 2, w["dy"] * w["length"] / 2
        a = (w["cx"] - hx, w["cy"] - hy)
        b = (w["cx"] + hx, w["cy"] + hy)
        if (round(a[0], 6), round(a[1], 6)) > (round(b[0], 6), round(b[1], 6)):
            a, b = b, a
        w["start"], w["end"] = a, b

    openings = []
    for key, kind in (("doors", "door"), ("windows", "window"),
                      ("openings", "opening")):
        for s in doc.get(key) or []:
            m = _matrix(s)
            dims = _dimensions(s)
            cx, cy = derot(*_plan_xy(m))
            openings.append({
                "kind": kind,
                "cx": cx, "cy": cy,
                "width": dims[0], "height": dims[1],
                "base": m[13] - dims[1] / 2.0,
                "parent": s.get("parentIdentifier"),
            })

    floors = []
    for s in doc.get("floors") or []:
        corners = s.get("polygonCorners")
        if isinstance(corners, list) and len(corners) >= 3:
            poly = [derot(c[0], -c[2]) for c in corners
                    if isinstance(c, list) and len(c) >= 3]
            if len(poly) >= 3:
                floors.append(poly)

    return {"walls": walls, "openings": openings, "floors": floors,
            "rotation_deg": round(math.degrees(rot), 2),
            "warnings": warnings}


def _shoelace(poly):
    area = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _attach(openings, walls, warnings):
    """Put each opening on its wall.

    parentIdentifier first — RoomPlan states the relationship and the
    statement beats any geometry. Proximity is the fallback for exporters
    that drop it: nearest wall by perpendicular distance, within ATTACH_M
    and within the wall's run.
    """
    by_id = {w["id"]: w for w in walls}
    placed = dropped = oversized = 0
    for o in openings:
        w = by_id.get(o["parent"]) if o["parent"] else None
        if w is None:
            best, best_d = None, ATTACH_M
            for cand in walls:
                ax, ay = cand["start"]
                ux = (cand["end"][0] - ax) / cand["length"]
                uy = (cand["end"][1] - ay) / cand["length"]
                t = (o["cx"] - ax) * ux + (o["cy"] - ay) * uy
                if -o["width"] / 2 <= t <= cand["length"] + o["width"] / 2:
                    px, py = ax + ux * t, ay + uy * t
                    d = math.hypot(o["cx"] - px, o["cy"] - py)
                    if d < best_d:
                        best, best_d = cand, d
            w = best
        if w is None:
            dropped += 1
            continue
        if o["width"] > w["length"]:
            # RoomPlan splits walls into segments on imperfect scans, so a
            # 0.9m door can arrive parented to (or nearest to) a 0.8m stub.
            # The clamp below keeps the full width, and Wall.add_opening
            # rightly refuses an opening wider than its wall — which used
            # to kill the whole job for a scan that is otherwise fine,
            # while an opening attached to NOTHING was merely warned about.
            # Same contract for both: drop it, and say so.
            oversized += 1
            continue
        ax, ay = w["start"]
        ux = (w["end"][0] - ax) / w["length"]
        uy = (w["end"][1] - ay) / w["length"]
        t = (o["cx"] - ax) * ux + (o["cy"] - ay) * uy
        along = max(0.0, min(w["length"] - o["width"], t - o["width"] / 2))
        sill = max(0.0, o["base"] - w["base"])
        if o["kind"] == "door" and sill < 0.15:
            # A door's few centimetres of "sill" is threshold and scan
            # noise, not a raised opening.
            sill = 0.0
        height = min(o["height"], w["height"] - sill)
        w.setdefault("_openings", []).append(
            {"kind": o["kind"], "along": along, "width": o["width"],
             "height": height, "sill": sill})
        placed += 1
    if dropped:
        warnings.append(
            f"{dropped} opening(s) could not be attached to any wall "
            f"(no parentIdentifier and nothing within {ATTACH_M}m) — they "
            f"are missing from the model and its quantities.")
    if oversized:
        warnings.append(
            f"{oversized} opening(s) are wider than the wall segment the "
            f"scan put them on (RoomPlan splits walls on imperfect scans) "
            f"— dropped, so they are missing from the model and its "
            f"quantities.")
    return placed


def to_model(parsed):
    """Parsed scan into the model3d dict every writer consumes."""
    warnings = list(parsed["warnings"])
    placed = _attach(parsed["openings"], parsed["walls"], warnings)

    walls = []
    for w in parsed["walls"]:
        wall = Wall(w["start"], w["end"], SCAN_WALL_THICKNESS_M,
                    w["height"], external=False)
        for o in w.get("_openings", []):
            wall.add_opening(o["kind"], o["along"], o["width"], o["height"],
                             o["sill"])
        walls.append(wall)

    if parsed["floors"]:
        floor_area = sum(_shoelace(p) for p in parsed["floors"])
        floor_basis = "measured from the scanned floor polygon"
    else:
        xs = [v for w in walls for v in (w.start[0], w.end[0])]
        ys = [v for w in walls for v in (w.start[1], w.end[1])]
        floor_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        floor_basis = ("the bounding box of the walls — the export carried "
                       "no floor polygon, so this OVERSTATES any room that "
                       "is not a rectangle")
        warnings.append(f"Floor area is {floor_basis}.")

    xs = [v for w in walls for v in (w.start[0], w.end[0])]
    ys = [v for w in walls for v in (w.start[1], w.end[1])]
    height = max(w.height for w in walls)

    model = {
        "source": "roomplan",
        "rooms": [],
        "walls": [w.as_dict() for w in walls],
        "storeys": 1,
        "storey_height_m": round(height, 3),
        "eaves_z_m": round(height, 3),
        "roof": None,
        "roof_quantities": None,
        "scan_rotation_deg": parsed["rotation_deg"],
        "extent_m": {"x": [round(min(xs), 3), round(max(xs), 3)],
                     "y": [round(min(ys), 3), round(max(ys), 3)],
                     "z": [0.0, round(height, 3)]},
        "totals": {
            "storeys": 1,
            "rooms": max(1, len(parsed["floors"])),
            "floor_area_m2": round(floor_area, 2),
            "walls": len(walls),
            "wall_length_m": round(sum(w.length_m for w in walls), 2),
            "wall_area_net_m2": round(sum(w.area_m2 for w in walls), 2),
            "doors": sum(1 for w in walls for o in w.openings
                         if o["kind"] == "door"),
            "windows": sum(1 for w in walls for o in w.openings
                           if o["kind"] == "window"),
            "ceiling_height_m": round(height, 3),
            "eaves_height_m": round(height, 3),
            "ridge_height_m": round(height, 3),
            "roof_sloped_area_m2": None,
        },
        "assumptions": [
            f"Wall thickness {SCAN_WALL_THICKNESS_M * 1000:.0f}mm nominal — "
            f"a scan sees one face of each wall and cannot measure through "
            f"it.",
            f"Floor area {floor_basis}.",
        ],
        "warnings": warnings + [
            "Built from an Apple RoomPlan scan: dimensions are the "
            "phone's LiDAR estimates, typically within a few centimetres "
            "on a wall run. Verify a critical dimension with a tape before "
            "cutting or ordering to it.",
            "A single-room scan sees inside faces only, so no wall here is "
            "known to be external — everything is quantified as the "
            "measured face, and no roof is modelled.",
        ],
    }
    if placed == 0 and parsed["openings"]:
        model["warnings"].append(
            "The export listed openings but none could be placed — door "
            "and window quantities are zero and wall areas are gross.")
    return model


# --- worker entry -----------------------------------------------------------


def fetch_export(spec, work_dir):
    """The export file named by the job, from URL or path, as a local path."""
    path = spec.get("roomplan_path")
    if path:
        if not os.path.exists(path):
            raise RoomPlanError(f"roomplan_path does not exist: {path}")
        return path
    url = spec.get("roomplan_url")
    if url:
        import validation
        response = validation.fetch_checked(url, field="roomplan_url")
        if response.status_code != 200:
            raise RoomPlanError(
                f"roomplan_url answered {response.status_code}")
        out = os.path.join(work_dir, "roomplan.json")
        with open(out, "wb") as f:
            f.write(response.content)
        return out
    raise RoomPlanError("no roomplan_url or roomplan_path in the job")
