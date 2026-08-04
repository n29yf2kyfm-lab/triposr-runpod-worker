"""Model Mode — a floor plan becomes a real 3D building.

The other direction from Structure Mode. Structure takes a point cloud of a
building that EXISTS and works out what is there. This takes a plan of a
building that does not exist yet — or one nobody has scanned — and builds
it: walls with real thickness, floor and ceiling slabs, door and window
openings cut through, exported as IFC and as a mesh anyone can open.

WHERE THE GEOMETRY COMES FROM, and why it is not traced off the picture.
Every UK drawing carries the instruction "DO NOT SCALE FROM THIS DRAWING —
all dimensions to be checked on site", and it means what it says: the
figured dimensions are the authority and the printed linework is an
illustration of them. A drawing office will happily issue a sheet whose
geometry is a millimetre out and whose dimension string is exact, because
the dimension is the contract. So this module builds from DIMENSIONS.

Tracing a scanned or photographed plan is a different job with a different
failure mode — extraction picks up dimension lines, hatching and text along
with the walls — and where that is wanted it belongs in drawing.py behind a
human confirming the scale, not here pretending to be survey.

WHAT THIS REFUSES TO DO. It will not invent a dimension. A room with no
stated size is not modelled at a guess; it is reported as missing, because
a plausible-looking wall in the wrong place is worse than a hole.
"""
import json
import math
import os

# UK domestic defaults, used only where the drawing does not say otherwise
# and always reported in the output so nothing is silently assumed.
DEFAULT_WALL_THICKNESS_M = 0.100        # internal stud partition over studs
DEFAULT_EXTERNAL_THICKNESS_M = 0.300    # cavity wall, brick + cavity + block
DEFAULT_CEILING_HEIGHT_M = 2.400        # Part M / typical new build
DEFAULT_SLAB_M = 0.150

# Approved Document M and BS 4787. A door is not a hole of arbitrary size.
DOOR_W_M, DOOR_H_M = 0.838, 1.981       # 838mm leaf — Part M minimum clear
WINDOW_H_M, WINDOW_SILL_M = 1.200, 0.900

MIN_ROOM_M2 = 0.8
MAX_ROOM_M2 = 500.0


class ModelError(ValueError):
    """Raised when a plan cannot be built into a model honestly.

    A model gets quantities taken off it and gets shown to a client as if it
    were the building. Guessing a dimension here propagates into both.
    """


# --- rooms ------------------------------------------------------------------

class Room:
    """One space, positioned by its bottom-left corner in metres."""

    def __init__(self, name, x, y, width, depth, height=None, kind="room"):
        if width <= 0 or depth <= 0:
            raise ModelError(f"{name}: a room needs a positive width and depth")
        area = width * depth
        if not MIN_ROOM_M2 <= area <= MAX_ROOM_M2:
            raise ModelError(
                f"{name}: {area:.1f} m2 is outside anything a room could be "
                f"({MIN_ROOM_M2}–{MAX_ROOM_M2} m2). Check the units — a "
                f"dimension read as metres when it was millimetres lands here.")
        self.name = name
        self.x, self.y = float(x), float(y)
        self.width, self.depth = float(width), float(depth)
        self.height = float(height or DEFAULT_CEILING_HEIGHT_M)
        self.kind = kind

    @property
    def area_m2(self):
        return self.width * self.depth

    @property
    def perimeter_m(self):
        return 2 * (self.width + self.depth)

    def corners(self):
        return [(self.x, self.y), (self.x + self.width, self.y),
                (self.x + self.width, self.y + self.depth),
                (self.x, self.y + self.depth)]

    def as_dict(self):
        return {"name": self.name, "kind": self.kind,
                "x": round(self.x, 3), "y": round(self.y, 3),
                "width_m": round(self.width, 3), "depth_m": round(self.depth, 3),
                "height_m": round(self.height, 3),
                "area_m2": round(self.area_m2, 2),
                "perimeter_m": round(self.perimeter_m, 2)}


def check_against_schedule(rooms, schedule, tolerance=0.05):
    """Compare modelled areas against the areas PRINTED on the drawing.

    The schedule is the drawing's own statement of what each room is, so it
    is the check that matters: if a modelled room disagrees with the figure
    beside it on the sheet, the dimensions were read wrong and every
    quantity downstream is wrong with them.
    """
    # Rooms are SUMMED BY NAME, because a real room is often not a
    # rectangle. An L-shaped kitchen is modelled as two rectangles sharing
    # one name, and comparing only the larger of them against the schedule
    # reported a 9.5% error on a room whose two parts add up exactly.
    out, worst = [], 0.0
    grouped = {}
    for r in rooms:
        grouped.setdefault(r.name.strip().lower(), []).append(r)

    for name, stated in (schedule or {}).items():
        parts = grouped.get(name.strip().lower())
        if not parts:
            out.append({"room": name, "stated_m2": stated, "modelled_m2": None,
                        "status": "not modelled"})
            continue
        modelled = sum(p.area_m2 for p in parts)
        error = abs(modelled - stated) / stated if stated else 0.0
        worst = max(worst, error)
        entry = {
            "room": name, "stated_m2": stated,
            "modelled_m2": round(modelled, 2),
            "error_pct": round(error * 100, 1),
            "status": "agrees" if error <= tolerance else "DISAGREES",
        }
        if len(parts) > 1:
            entry["parts"] = len(parts)
        out.append(entry)
    return {"rooms": out,
            "worst_error_pct": round(worst * 100, 1),
            "within_tolerance": worst <= tolerance,
            "tolerance_pct": round(tolerance * 100, 1)}


# --- walls ------------------------------------------------------------------

class Wall:
    """A wall as a centreline plus a thickness and a height."""

    def __init__(self, start, end, thickness, height, external=False):
        self.start, self.end = tuple(start), tuple(end)
        self.thickness = float(thickness)
        self.height = float(height)
        self.external = bool(external)
        self.openings = []

    @property
    def length_m(self):
        return math.hypot(self.end[0] - self.start[0],
                          self.end[1] - self.start[1])

    @property
    def area_m2(self):
        gross = self.length_m * self.height
        return max(0.0, gross - sum(o["width"] * o["height"]
                                    for o in self.openings))

    def add_opening(self, kind, along_m, width, height, sill=0.0):
        if along_m < 0 or along_m + width > self.length_m + 1e-6:
            raise ModelError(
                f"an opening {width:.2f}m wide at {along_m:.2f}m does not fit "
                f"in a wall {self.length_m:.2f}m long")
        self.openings.append({"kind": kind, "along": float(along_m),
                              "width": float(width), "height": float(height),
                              "sill": float(sill)})

    def as_dict(self):
        return {"start": [round(v, 3) for v in self.start],
                "end": [round(v, 3) for v in self.end],
                "length_m": round(self.length_m, 3),
                "thickness_m": round(self.thickness, 3),
                "height_m": round(self.height, 3),
                "external": self.external,
                "net_area_m2": round(self.area_m2, 2),
                "openings": self.openings}


def walls_from_rooms(rooms, internal=DEFAULT_WALL_THICKNESS_M,
                     external=DEFAULT_EXTERNAL_THICKNESS_M):
    """Every room edge as a wall, with shared edges built once.

    Two rooms back to back share one wall, not two. Building both is the
    classic plan-to-model error: it doubles the plasterboard, doubles the
    paint and puts 100mm of nothing between the rooms.
    """
    seen, walls = {}, []
    for room in rooms:
        pts = room.corners()
        for i in range(4):
            a, b = pts[i], pts[(i + 1) % 4]
            key = tuple(sorted([(round(a[0], 3), round(a[1], 3)),
                                (round(b[0], 3), round(b[1], 3))]))
            if key in seen:
                continue
            wall = Wall(a, b, internal, room.height, external=True)
            seen[key] = wall
            walls.append(wall)

    # INTERNAL OR EXTERNAL IS DECIDED BY WHAT IS ON THE OTHER SIDE, not by
    # whether two rooms happen to share an identical edge.
    #
    # Matching edges exactly only works when rooms are drawn flush. A real
    # plan has corridors, service risers and set-backs, so almost no two
    # rooms share a coincident edge — and keying on that marked EVERY wall
    # external. The first run of this module produced 52 windows and no
    # doors for a 16-room flat conversion, which is a nonsense anybody would
    # spot, and a nonsense that would price 52 windows.
    #
    # Stepping off the wall perpendicular and asking whether that lands
    # inside another room answers the real question.
    for wall in walls:
        (ax, ay), (bx, by) = wall.start, wall.end
        length = wall.length_m
        if length <= 0:
            continue
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        nx, ny = -(by - ay) / length, (bx - ax) / length
        step = max(internal, external) + 0.05
        both = 0
        for sign in (1, -1):
            px, py = mx + nx * step * sign, my + ny * step * sign
            if any(r.x - 1e-6 <= px <= r.x + r.width + 1e-6
                   and r.y - 1e-6 <= py <= r.y + r.depth + 1e-6
                   for r in rooms):
                both += 1
        wall.external = both < 2

    for wall in walls:
        wall.thickness = external if wall.external else internal
    return walls


# --- roof -------------------------------------------------------------------

# UK pitches, and why they are not free choices. Below about 15 degrees an
# interlocking tile will not shed water reliably and BS 5534 wants a
# different covering; above about 55 degrees tiles need mechanical fixing
# throughout. A drawing that states a pitch outside this is saying something
# unusual and worth reading twice.
MIN_PITCH_DEG, MAX_PITCH_DEG = 12.0, 60.0
DEFAULT_PITCH_DEG = 35.0
DEFAULT_EAVES_OVERHANG_M = 0.30

# How far a roof can span in ONE range before it stops being a roof and
# becomes a structure. A trussed rafter goes to roughly 11m, and beyond
# that a domestic or small commercial building is not roofed in one span at
# all — it is DOUBLE-PILE: two or more parallel ranges with a valley gutter
# down between them. That is why Victorian pubs, terraces and mills read as
# an M from the end.
#
# Ignoring this is not a cosmetic error. A single hip over a 14.3m footprint
# at 35 degrees rises 5.0m, putting the ridge 5 metres above the wall head
# on a building whose storeys are 2.75m — a roof about two storeys tall,
# which is instantly wrong to anybody who has looked at a building. Split
# into two ranges the same footprint rises 2.5m, which is what is actually
# built.
MAX_ROOF_SPAN_M = 9.0


def roof_over(x0, y0, x1, y1, pitch_deg=DEFAULT_PITCH_DEG, kind="hipped",
              overhang=DEFAULT_EAVES_OVERHANG_M, base_z=0.0,
              max_span=MAX_ROOF_SPAN_M):
    """A pitched roof over a rectangular footprint.

    THE NUMBER THAT MATTERS IS THE SLOPED AREA, not the plan area, and the
    difference is the whole reason roof quantities go wrong. A roof covers
    more material than its footprint by exactly 1/cos(pitch): at 35 degrees
    that is 22% more, at 45 it is 41% more. Order tiles off the plan area
    and you are a fifth short on a job you have already priced.

    Hipped and gabled are both here because they carry different quantities
    — a hip needs hip tiles and cut tiles down both ends, a gable needs
    verge and no hips at all — and getting that wrong is a real bill.

    A footprint too deep for one span becomes several parallel RANGES with
    valley gutters between them. The sloped area is unchanged by that —
    every plane is still at the same pitch — but the ridge height, the ridge
    run, the hip count and the valley length all change, and those are four
    separate lines on the quote.
    """
    if not MIN_PITCH_DEG <= pitch_deg <= MAX_PITCH_DEG:
        raise ModelError(
            f"a {pitch_deg:.0f} degree pitch is outside the {MIN_PITCH_DEG:.0f}"
            f"–{MAX_PITCH_DEG:.0f} degree range UK tiled roofs are built in. "
            f"Below that a tile will not shed water; above it every tile "
            f"needs mechanically fixing. Check the elevation.")
    if kind not in ("hipped", "gabled"):
        raise ModelError("roof kind must be 'hipped' or 'gabled'")

    x0, x1 = x0 - overhang, x1 + overhang
    y0, y1 = y0 - overhang, y1 + overhang
    width, depth = x1 - x0, y1 - y0
    if width <= 0 or depth <= 0:
        raise ModelError("a roof needs a positive footprint")

    theta = math.radians(pitch_deg)
    # The ridge runs along the LONGER axis; the slope climbs across the
    # shorter one. A footprint too deep to span in one go is split into that
    # many parallel ranges across the short axis.
    along_x = width >= depth
    total_span = depth if along_x else width
    run = width if along_x else depth          # length of a ridge, gable end
    n_ranges = max(1, int(math.ceil(total_span / max_span - 1e-9)))
    span = total_span / n_ranges
    rise = (span / 2.0) * math.tan(theta)
    ridge_z = base_z + rise

    # Each range: its band across the short axis, and its ridge line.
    ranges, ridges, hips, valleys = [], [], [], []
    lo0 = (y0 if along_x else x0)
    for i in range(n_ranges):
        lo = lo0 + i * span
        hi = lo + span
        mid = (lo + hi) / 2.0
        if kind == "hipped":
            inset = span / 2.0
            ends = (x0 + inset, x1 - inset) if along_x else (y0 + inset,
                                                             y1 - inset)
        else:                               # gabled — ridge runs wall to wall
            ends = (x0, x1) if along_x else (y0, y1)
        if along_x:
            band = {"y": [round(lo, 3), round(hi, 3)],
                    "x": [round(x0, 3), round(x1, 3)]}
            line = [(ends[0], mid), (ends[1], mid)]
        else:
            band = {"x": [round(lo, 3), round(hi, 3)],
                    "y": [round(y0, 3), round(y1, 3)]}
            line = [(mid, ends[0]), (mid, ends[1])]
        ridges.append(line)
        ranges.append({"band_m": band,
                       "ridge": [[round(v, 3) for v in p] for p in line],
                       "span_m": round(span, 3)})
        # A hip runs from each ridge end down to a corner of its own range.
        # Its true length is the 3D diagonal, not the plan diagonal.
        if kind == "hipped":
            half = span / 2.0
            hips += [math.hypot(math.hypot(half, half), rise)] * 4
        # Where two ranges abut there is a valley gutter at eaves level,
        # running the full length of the building. It is not eaves and it is
        # not ridge: it is a lined gutter, and it is the line on a re-roof
        # that leaks if it is left off the quote.
        if i:
            valleys.append(run)

    ridge = ridges[0]
    ridge_len = sum(math.hypot(r[1][0] - r[0][0], r[1][1] - r[0][1])
                    for r in ridges)
    plan_area = width * depth
    # Unchanged by the split: every plane is still at the same pitch, so the
    # covering is the same. Only the ridge height and the linear items move.
    sloped_area = plan_area / math.cos(theta)

    return {
        "kind": kind,
        "pitch_deg": round(pitch_deg, 1),
        "footprint_m": {"x": [round(x0, 3), round(x1, 3)],
                        "y": [round(y0, 3), round(y1, 3)]},
        "eaves_z_m": round(base_z, 3),
        "ridge_z_m": round(ridge_z, 3),
        "rise_m": round(rise, 3),
        "ranges": n_ranges,
        "span_m": round(span, 3),
        "range_list": ranges,
        "ridge": [[round(v, 3) for v in p] for p in ridge],
        "ridge_m": round(ridge_len, 2),
        "hip_m": round(sum(hips), 2),
        "valley_m": round(sum(valleys), 2),
        "eaves_m": round(2 * (width + depth), 2),
        "verge_m": round(2 * total_span, 2) if kind == "gabled" else 0.0,
        "plan_area_m2": round(plan_area, 2),
        "sloped_area_m2": round(sloped_area, 2),
        "uplift_pct": round((sloped_area / plan_area - 1) * 100, 1),
        "overhang_m": round(overhang, 3),
        "along_x": along_x,
        "note": (f"Sloped area is {sloped_area:.1f} m2 against a "
                 f"{plan_area:.1f} m2 footprint — {(sloped_area/plan_area-1)*100:.0f}% "
                 f"more material than the plan area suggests. Ordering off "
                 f"the footprint is how a roof comes up short."),
        "range_note": (
            f"{total_span:.1f}m is more than a roof spans in one go, so this "
            f"is {n_ranges} ranges of {span:.1f}m with "
            f"{n_ranges - 1} valley gutter{'s' if n_ranges > 2 else ''} "
            f"between them — the ridge sits {rise:.2f}m above the wall head "
            f"instead of {total_span / 2 * math.tan(theta):.2f}m."
        ) if n_ranges > 1 else None,
    }


def roof_quantities(roof, covering="concrete_interlocking"):
    """Roof takeoff, in the shape Price Mode already accepts."""
    a = roof["sloped_area_m2"]
    out = {
        "sloped_area_m2": a,
        "plan_area_m2": roof["plan_area_m2"],
        "ridge_m": roof["ridge_m"],
        "hip_m": roof["hip_m"],
        "valley_m": roof["valley_m"],
        "eaves_m": roof["eaves_m"],
        "verge_m": roof["verge_m"],
        "covering": covering,
        "materials": {
            "membrane_m2": round(a * 1.15, 1),      # laps
            "battens_m": round(a / 0.30, 1),        # 300mm gauge
            "ridge_units": round((roof["ridge_m"] + roof["hip_m"]) / 0.30, 0),
        },
    }
    # A valley gutter is lined, not tiled — GRP or lead over a valley board,
    # with a 10% allowance for the laps and the ends. Leaving it off is the
    # cheapest line on the quote and the first thing to leak.
    if roof["valley_m"]:
        out["materials"]["valley_lining_m"] = round(roof["valley_m"] * 1.1, 1)
    return out


# Above this, the exact union costs more than the answer is worth — the check
# is a yes/no about whether a plan looks partial, not a quantity anybody
# orders from. Past it, fall back to the sum and cap it, which can only ever
# understate how empty the plate is.
UNION_EXACT_MAX_ROOMS = 400


def _union_area(rooms):
    """Area covered by the rooms, counting overlaps once.

    Sweeps the x edges, and for each vertical slab merges the y intervals of
    the rooms crossing it. Exact for axis-aligned rectangles, which is all a
    plan holds, and it needs no geometry library.
    """
    if not rooms:
        return 0.0
    if len(rooms) > UNION_EXACT_MAX_ROOMS:
        total = sum(r.area_m2 for r in rooms)
        xs = [c[0] for r in rooms for c in r.corners()]
        ys = [c[1] for r in rooms for c in r.corners()]
        box = (max(xs) - min(xs)) * (max(ys) - min(ys))
        return min(total, box) if box > 0 else total

    edges = sorted({r.x for r in rooms} | {r.x + r.width for r in rooms})
    area = 0.0
    for i in range(len(edges) - 1):
        left, right = edges[i], edges[i + 1]
        width = right - left
        if width <= 0:
            continue
        mid = (left + right) / 2.0
        spans = sorted((r.y, r.y + r.depth) for r in rooms
                       if r.x <= mid <= r.x + r.width)
        covered = 0.0
        run_lo = run_hi = None
        for lo, hi in spans:
            if run_hi is None or lo > run_hi:
                if run_hi is not None:
                    covered += run_hi - run_lo
                run_lo, run_hi = lo, hi
            elif hi > run_hi:
                run_hi = hi
        if run_hi is not None:
            covered += run_hi - run_lo
        area += width * covered
    return area


# --- the model --------------------------------------------------------------

def build(rooms, schedule=None, wall_openings=True, storeys=1,
          storey_height=None, roof=None):
    """Rooms in, a whole building out.

    `storeys` repeats the floor plate upward. That is what a conversion of
    this kind actually is — the same structural footprint, floor after
    floor — and it is honest as long as the output says the upper floors
    were assumed rather than drawn, which it does.

    `roof` is a dict of {pitch_deg, kind, overhang} or None for a flat top.
    """
    if not rooms:
        raise ModelError("no rooms supplied — there is nothing to build")
    if storeys < 1 or storeys > 20:
        raise ModelError(f"{storeys} storeys is not a building")

    walls = walls_from_rooms(rooms)

    if wall_openings:
        for wall in walls:
            if wall.external and wall.length_m >= 1.8:
                wall.add_opening("window", wall.length_m / 2 - 0.6, 1.2,
                                 WINDOW_H_M, WINDOW_SILL_M)
            elif not wall.external and wall.length_m >= DOOR_W_M + 0.4:
                wall.add_opening("door", 0.2, DOOR_W_M, DOOR_H_M)

    height = max(r.height for r in rooms)
    # Floor to floor is the ceiling height plus the floor zone — joists,
    # deck and ceiling. Ignoring it stacks the storeys 350mm too close and
    # puts the roof a metre low on a three-storey block.
    floor_zone = 0.35
    per_storey = float(storey_height or (height + floor_zone))
    xs = [c[0] for r in rooms for c in r.corners()]
    ys = [c[1] for r in rooms for c in r.corners()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    # The eaves sit on TOP OF THE TOPMOST WALL, not a floor zone above it.
    # `per_storey * storeys` reads naturally and is wrong by exactly one
    # floor zone: it leaves the roof floating 350mm clear of the walls it is
    # supposed to be bearing on, which is a visible hole in the model and a
    # wall plate nailed to fresh air.
    eaves_z = per_storey * (storeys - 1) + height

    roof_model = None
    if roof:
        roof_model = roof_over(
            x0, y0, x1, y1,
            pitch_deg=roof.get("pitch_deg", DEFAULT_PITCH_DEG),
            kind=roof.get("kind", "hipped"),
            overhang=roof.get("overhang_m", DEFAULT_EAVES_OVERHANG_M),
            base_z=eaves_z)

    top = roof_model["ridge_z_m"] if roof_model else eaves_z

    result = {
        "rooms": [r.as_dict() for r in rooms],
        "walls": [w.as_dict() for w in walls],
        "storeys": storeys,
        "storey_height_m": round(per_storey, 3),
        "eaves_z_m": round(eaves_z, 3),
        "roof": roof_model,
        "roof_quantities": roof_quantities(roof_model) if roof_model else None,
        "extent_m": {"x": [round(x0, 3), round(x1, 3)],
                     "y": [round(y0, 3), round(y1, 3)],
                     "z": [0.0, round(top, 3)]},
        "totals": {
            "storeys": storeys,
            "rooms": len(rooms) * storeys,
            "floor_area_m2": round(sum(r.area_m2 for r in rooms) * storeys, 2),
            "walls": len(walls) * storeys,
            "wall_length_m": round(sum(w.length_m for w in walls) * storeys, 2),
            "wall_area_net_m2": round(
                sum(w.area_m2 for w in walls) * storeys, 2),
            "doors": sum(1 for w in walls for o in w.openings
                         if o["kind"] == "door") * storeys,
            "windows": sum(1 for w in walls for o in w.openings
                           if o["kind"] == "window") * storeys,
            "ceiling_height_m": round(height, 3),
            "eaves_height_m": round(eaves_z, 3),
            "ridge_height_m": round(top, 3),
            "roof_sloped_area_m2": (roof_model or {}).get("sloped_area_m2"),
        },
        "assumptions": [
            f"Internal walls {DEFAULT_WALL_THICKNESS_M * 1000:.0f}mm, external "
            f"{DEFAULT_EXTERNAL_THICKNESS_M * 1000:.0f}mm — the drawing does "
            f"not state them.",
            f"Ceiling height {DEFAULT_CEILING_HEIGHT_M:.2f}m where not given.",
            f"Doors {DOOR_W_M * 1000:.0f}mm (Part M clear width), windows "
            f"{WINDOW_H_M:.1f}m high at {WINDOW_SILL_M:.1f}m sill.",
        ],
        "warnings": [
            "Built from the drawing's FIGURED DIMENSIONS, not traced off the "
            "linework — which is what the drawing itself instructs. It is as "
            "right as those dimensions are, and no righter.",
            "Rooms are modelled as rectangles. A bay, a splay or a curved "
            "return is not in this model.",
        ],
    }
    if storeys > 1:
        result["warnings"].append(
            f"Only one floor plate was supplied, repeated for all {storeys} "
            f"storeys at {per_storey:.2f}m floor to floor. The upper floors "
            f"are ASSUMED to match, not drawn — check them against their own "
            f"plans before taking a quantity off them.")
    if roof_model:
        result["warnings"].append(roof_model["note"])
        # THE ENVELOPE IS NOT THE BUILDING, and nothing here checks that it
        # is. The rooms get verified against the drawing's own schedule; the
        # rectangle drawn round them gets verified against nothing. Roof The
        # a real first-floor plan and you get a roof over 229.9 m2, when the
        # building on the ground is 369.6 m2 and L-shaped round a corner —
        # every roof quantity below is then for a building that is not there.
        #
        # Cheap and reliable tell: rooms only fill a rectangular plate if the
        # plan is the whole floor. A partial plan, a wing, or an L leaves the
        # bounding box well short.
        #
        # MEASURED AS A UNION, NOT A SUM. Summing room areas is the obvious
        # thing and it is wrong in the one direction that matters: two rooms
        # that overlap — an L-shaped space entered as two overlapping
        # rectangles, or a room typed in twice — push the figure past 100%
        # and switch the warning off. The check exists to catch a plan that
        # is missing area; a bug that hides it on a plan with duplicated
        # area is worse than not having the check.
        box = (x1 - x0) * (y1 - y0)
        fill = _union_area(rooms) / box if box > 0 else 1.0
        result["roof"]["plan_fill_pct"] = round(fill * 100, 1)
        if fill < 0.75:
            result["warnings"].append(
                f"THE ROOF IS OVER A BOUNDING BOX, NOT A MEASURED FOOTPRINT. "
                f"The rooms supplied fill only {fill * 100:.0f}% of the "
                f"rectangle drawn round them, so this is a partial plan, a "
                f"wing, or an L-shaped building squared off. The rooms are "
                f"checked against the drawing; this rectangle is checked "
                f"against nothing. Confirm the real footprint before taking "
                f"a roof quantity off it.")
        result["assumptions"].append(
            f"Roof {roof_model['kind']} at {roof_model['pitch_deg']:.0f} "
            f"degrees with a {roof_model['overhang_m'] * 1000:.0f}mm eaves "
            f"overhang — read off the elevation, not stated as a figure.")

    if schedule:
        result["schedule_check"] = check_against_schedule(rooms, schedule)
    return result


# --- export -----------------------------------------------------------------

def write_obj(model, path):
    """Wavefront OBJ — opens in anything, no library needed.

    Deliberately dependency-free. IFC is the right interchange format for a
    building and write_ifc below produces one, but IFC needs software to
    read; an OBJ opens on a phone, in a browser, and in every 3D tool there
    is, which matters when the point is showing somebody their building.
    """
    verts, faces, groups = [], [], []

    def box(x0, y0, z0, x1, y1, z1, name):
        base = len(verts) + 1
        for x, y, z in [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]:
            verts.append((x, z, -y))         # OBJ is Y-up; plan Y runs into -Z
        groups.append((name, len(faces)))
        for f in [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                  (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]:
            faces.append(tuple(base + i for i in f))

    x0, x1 = model["extent_m"]["x"]
    y0, y1 = model["extent_m"]["y"]
    storeys = model.get("storeys", 1)
    per = model.get("storey_height_m", DEFAULT_CEILING_HEIGHT_M)

    # EVERY storey, not just the first. The plan is one floor plate; the
    # building is that plate repeated, and writing only the ground floor
    # produced a three-storey block as a bungalow.
    for level in range(storeys):
        z = level * per
        box(x0, y0, z - DEFAULT_SLAB_M, x1, y1, z, f"slab_L{level}")
        for i, w in enumerate(model["walls"]):
            (ax, ay), (bx, by) = w["start"], w["end"]
            t = w["thickness_m"] / 2.0
            if abs(bx - ax) >= abs(by - ay):        # runs along x
                lo, hi = sorted((ax, bx))
                for j, (s, e, zlo, zhi) in enumerate(
                        _split_for_openings(lo, hi, w)):
                    box(s, ay - t, z + zlo, e, ay + t, z + zhi,
                        f"L{level}_wall_{i}_{j}")
            else:                                   # runs along y
                lo, hi = sorted((ay, by))
                for j, (s, e, zlo, zhi) in enumerate(
                        _split_for_openings(lo, hi, w)):
                    box(ax - t, s, z + zlo, ax + t, e, z + zhi,
                        f"L{level}_wall_{i}_{j}")

    roof = model.get("roof")
    if roof:
        _roof_faces(roof, verts, faces, groups)

    with open(path, "w") as f:
        f.write("# Building model — figured dimensions, metres\n")
        f.write(f"# {model['totals']['rooms']} rooms, "
                f"{model['totals']['floor_area_m2']} m2\n")
        for v in verts:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        by_index = {i: n for n, i in groups}
        for i, face in enumerate(faces):
            if i in by_index:
                f.write(f"g {by_index[i]}\n")
            f.write("f " + " ".join(str(v) for v in face) + "\n")
    return path


def _roof_faces(roof, verts, faces, groups):
    """The roof as real sloped surfaces — four planes per hipped range.

    Written as actual pitched planes rather than a box with a lid, because
    the whole point of the roof is that it is not flat: a viewer showing a
    flat top would hide the 22% of extra covering the sloped area accounts
    for, and that is the number a builder orders from.

    Every RANGE is drawn. A double-pile roof drawn as one range is the same
    error as a three-storey block drawn as a bungalow — it looks fine and it
    is a different building.
    """
    ez, rz = roof["eaves_z_m"], roof["ridge_z_m"]
    along_x = roof["along_x"]

    def V(x, y, z):
        verts.append((x, z, -y))          # OBJ Y-up, plan Y into -Z
        return len(verts)

    groups.append(("roof", len(faces)))
    for band in roof.get("range_list") or [
            {"band_m": roof["footprint_m"], "ridge": roof["ridge"]}]:
        bx0, bx1 = band["band_m"]["x"]
        by0, by1 = band["band_m"]["y"]
        (r0x, r0y), (r1x, r1y) = band["ridge"]

        a, b = V(bx0, by0, ez), V(bx1, by0, ez)
        c, d = V(bx1, by1, ez), V(bx0, by1, ez)
        r0, r1 = V(r0x, r0y, rz), V(r1x, r1y, rz)

        if along_x:
            faces.append((a, b, r1, r0))          # front slope
            faces.append((c, d, r0, r1))          # back slope
            faces.append((d, a, r0))              # left end
            faces.append((b, c, r1))              # right end
        else:
            faces.append((b, c, r1, r0))
            faces.append((d, a, r0, r1))
            faces.append((a, b, r0))
            faces.append((c, d, r1))


def _split_for_openings(lo, hi, wall):
    """A wall with a hole in it is several boxes, not one.

    Returns [(from, to, z_low, z_high)]. Above a door there is still a
    lintel; above a window there is a lintel and below it a spandrel, and
    leaving either out is how a model ends up with daylight through the
    brickwork.
    """
    h = wall["height_m"]
    if not wall["openings"]:
        return [(lo, hi, 0.0, h)]
    out, cursor = [], lo
    for o in sorted(wall["openings"], key=lambda o: o["along"]):
        s = lo + o["along"]
        e = s + o["width"]
        if s > cursor:
            out.append((cursor, s, 0.0, h))
        sill = o.get("sill", 0.0)
        if sill > 0:
            out.append((s, e, 0.0, sill))                 # under a window
        top = sill + o["height"]
        if top < h:
            out.append((s, e, top, h))                    # lintel over
        cursor = e
    if cursor < hi:
        out.append((cursor, hi, 0.0, h))
    return out


def write_ifc(model, path, project_name="Modelled Building"):
    """IFC4, via the same lazy import discipline as structure.py."""
    try:
        import ifcopenshell
        import ifcopenshell.api.root
        import ifcopenshell.api.project
        import ifcopenshell.api.unit
        import ifcopenshell.api.context
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.spatial
        import ifcopenshell.api.geometry
    except ImportError:
        raise ModelError(
            "ifcopenshell is not installed, so IFC cannot be written. The "
            "OBJ and the quantities above are unaffected.")

    run = ifcopenshell.api.run
    f = ifcopenshell.api.project.create_file(version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject",
                  name=project_name)
    metre = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT",
                                              prefix=None)
    ifcopenshell.api.unit.assign_unit(f, units=[metre])
    ctx = run("context.add_context", f, context_type="Model")
    body = run("context.add_context", f, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW",
               parent=ctx)
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", f, ifc_class="IfcBuilding",
                   name=project_name)
    storey = run("root.create_entity", f, ifc_class="IfcBuildingStorey",
                 name="First Floor")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)
    run("aggregate.assign_object", f, products=[storey],
        relating_object=building)

    for i, w in enumerate(model["walls"]):
        (ax, ay), (bx, by) = w["start"], w["end"]
        length = w["length_m"]
        if length <= 0:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        el = run("root.create_entity", f, ifc_class="IfcWall",
                 name=f"Wall {i} {length:.2f}m")
        run("spatial.assign_container", f, products=[el],
            relating_structure=storey)
        run("geometry.edit_object_placement", f, product=el, matrix=(
            (ux, -uy, 0.0, ax), (uy, ux, 0.0, ay),
            (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        profile = f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA",
            XDim=float(length), YDim=float(w["thickness_m"]),
            Position=f.create_entity("IfcAxis2Placement2D",
                Location=f.create_entity("IfcCartesianPoint",
                                         Coordinates=(length / 2.0, 0.0))))
        solid = f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile,
            Position=f.create_entity("IfcAxis2Placement3D",
                Location=f.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0))),
            ExtrudedDirection=f.create_entity("IfcDirection",
                                              DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(w["height_m"]))
        shape = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=body,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid",
            Items=[solid])
        run("geometry.assign_representation", f, product=el,
            representation=shape)

    for room in model["rooms"]:
        space = run("root.create_entity", f, ifc_class="IfcSpace",
                    name=room["name"])
        # IfcSpace is a spatial STRUCTURE element: it is AGGREGATED into the
        # storey, not contained in it. assign_container raises here.
        run("aggregate.assign_object", f, products=[space],
            relating_object=storey)

    f.write(path)
    return path


# --- handler entry point ----------------------------------------------------

def run_mode(spec, prog, output_dir):
    """Model mode entry point."""
    import paths

    prog.stage("reading")
    plan = spec.get("plan") or {}
    entries = plan.get("rooms") or spec.get("rooms")
    if not entries:
        raise ModelError(
            "model mode needs a plan: a list of rooms, each with a name, an "
            "x/y position in metres and a width and depth. Those come from "
            "the drawing's figured dimensions, not from tracing it.")

    rooms = []
    for e in entries:
        rooms.append(Room(
            name=e.get("name") or "room",
            x=e.get("x", 0.0), y=e.get("y", 0.0),
            width=e.get("width_m") or e.get("width"),
            depth=e.get("depth_m") or e.get("depth"),
            height=e.get("height_m") or plan.get("height_m"),
            kind=e.get("kind", "room")))

    # A schedule given directly wins; otherwise read the drawing's own.
    sched = plan.get("schedule")
    sched_note = None
    src = spec.get("schedule_path") or spec.get("schedule_url")
    if not sched and src:
        try:
            import schedule as _sched
            parsed = _sched.parse(src)
            lvl = spec.get("schedule_level")
            sched = _sched.as_check_input(parsed, level_no=lvl)
            sched_note = (
                f"Room schedule read off the drawing: {len(parsed['rooms'])} "
                f"rooms across {len(_sched.levels(parsed))} level(s)"
                + (f", narrowed to level {lvl}." if lvl else "."))
        except Exception as e:
            sched_note = (f"Could not read a room schedule from the drawing "
                          f"({type(e).__name__}: {e}). The model is built "
                          f"from the dimensions either way, but nothing "
                          f"independent has checked it.")

    prog.stage("building")
    model = build(rooms, schedule=sched,
                  storeys=int(plan.get("storeys", 1)),
                  storey_height=plan.get("storey_height_m"),
                  roof=plan.get("roof"))

    if sched_note:
        model["warnings"].append(sched_note)

    prog.stage("exporting")
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "model"
    artifacts = []

    obj_path = os.path.join(directory, f"{scan}.obj")
    write_obj(model, obj_path)
    artifacts.append((obj_path, f"models/{scan}.obj", None))
    model["obj"] = True

    ifc_path = os.path.join(directory, f"{scan}.ifc")
    try:
        write_ifc(model, ifc_path, project_name=scan)
        artifacts.append((ifc_path, f"models/{scan}.ifc", None))
        model["ifc"] = True
    except Exception as e:
        model["ifc"] = False
        model["warnings"].append(
            f"IFC export failed ({type(e).__name__}: {e}). The OBJ and every "
            f"quantity above are unaffected.")

    json_path = os.path.join(directory, f"{scan}.model.json")
    with open(json_path, "w") as f:
        json.dump(model, f, indent=2)
    artifacts.append((json_path, f"models/{scan}.json", None))

    return artifacts, {"model": model, "warnings": model["warnings"]}


run = run_mode
