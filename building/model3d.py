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
# Roughly how much frontage one window serves. Rule-placed windows are a
# stand-in until an elevation is read off a photograph, and the stand-in has
# to put ONE IN EVERY ROOM — an escape check is meaningless if a bedroom at
# the end of a long wall never gets an opening at all.
WINDOW_PITCH_M = 3.500

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

    def __init__(self, name, x, y, width, depth, height=None, kind="room",
                 storeys=None, base_level=0):
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
        # HOW MANY STOREYS THIS BLOCK IS, when the building is not uniform.
        # None means "as many as the building has". A single-storey rear
        # extension on a two-storey house is the commonest plan there is, and
        # without this the floor plate simply repeats: the extension came
        # back with a phantom first floor sitting on it, and a 350mm band of
        # daylight where its 2.4m walls stopped under a 2.75m storey.
        self.storeys = None if storeys is None else int(storeys)
        # WHICH STOREY THIS BLOCK STARTS ON. 0 is the ground floor. A first-
        # floor extension over an existing single-storey side element — very
        # common on a 1930s semi with a garage or utility down the side — is
        # base_level 1, and without this it can only be modelled as a
        # two-storey block, which prices a ground floor that is already built.
        self.base_level = int(base_level)

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
                "storeys": self.storeys,
                "base_level": self.base_level,
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
        # WHICH SIDE IS THE STREET. The wall's left normal (-uy, ux) points
        # INWARD for a room wound counter-clockwise, which Room.corners() is.
        # Every exporter that shaded one face brick and the other plaster
        # assumed +n was outside, so every GLB this module has produced put
        # the brickwork on the inside and the plaster on the street. It is
        # invisible in the numbers and obvious the moment the model is drawn.
        # walls_from_rooms probes for the real answer and sets this.
        self.outward = 1
        # None = present on every storey. Set from the room that raised it.
        self.storeys = None
        # First storey this wall exists on. Non-zero for a block built over
        # something that is already there.
        self.base_level = 0
        # How many storeys have a room on BOTH sides. Above this an
        # "internal" wall faces the weather and is built as such.
        self.shared_storeys = None

    @property
    def length_m(self):
        return math.hypot(self.end[0] - self.start[0],
                          self.end[1] - self.start[1])

    @property
    def area_m2(self):
        gross = self.length_m * self.height
        return max(0.0, gross - sum(o["width"] * o["height"]
                                    for o in self.openings))

    def add_opening(self, kind, along_m, width, height, sill=0.0,
                    level=None):
        """`level` pins an opening to ONE storey (0-based) when the floor
        plate repeats. Walls are written once and redrawn per storey, so an
        un-pinned front door repeats up the building — a floating door on
        every upper floor, which is how the first render of a real house
        type came back with no door at all: nobody had added one because
        there was no way to add it only once."""
        if along_m < 0 or along_m + width > self.length_m + 1e-6:
            raise ModelError(
                f"an opening {width:.2f}m wide at {along_m:.2f}m does not fit "
                f"in a wall {self.length_m:.2f}m long")
        self.openings.append({"kind": kind, "along": float(along_m),
                              "width": float(width), "height": float(height),
                              "sill": float(sill),
                              "level": None if level is None else int(level)})

    def as_dict(self):
        return {"start": [round(v, 3) for v in self.start],
                "end": [round(v, 3) for v in self.end],
                "length_m": round(self.length_m, 3),
                "thickness_m": round(self.thickness, 3),
                "height_m": round(self.height, 3),
                "external": self.external,
                "outward": self.outward,
                "storeys": self.storeys,
                "base_level": self.base_level,
                "shared_storeys": self.shared_storeys,
                # A WALL CAN BE "EXTERNAL" AND FACE A CAVITY. void_facing is
                # computed at build time and was then thrown away here, so
                # every consumer of the exported JSON — glazing checks, heat
                # loss, the viewer — treated a 100mm void strip as facade.
                "void_facing": bool(getattr(self, "void_facing", False)),
                "party": bool(getattr(self, "party", False)),
                "net_area_m2": round(self.area_m2, 2),
                "openings": self.openings}


def _wall_on_level(wall, level):
    """Is this wall built on this storey?

    A wall raised by a single-storey block exists on the ground floor only.
    Repeating it up the building is what put a first floor on every rear
    extension this module has ever modelled.
    """
    if isinstance(wall, dict):
        n, base = wall.get("storeys"), wall.get("base_level") or 0
    else:
        n, base = wall.storeys, getattr(wall, "base_level", 0)
    if level < base:
        return False
    return n is None or level < base + n


def walls_from_rooms(rooms, internal=DEFAULT_WALL_THICKNESS_M,
                     external=DEFAULT_EXTERNAL_THICKNESS_M):
    """Every room edge as a wall, with shared edges built once.

    Two rooms back to back share one wall, not two. Building both is the
    classic plan-to-model error: it doubles the plasterboard, doubles the
    paint and puts 100mm of nothing between the rooms.
    """
    # A SHARED EDGE IS ONLY SHARED IF BOTH SIDES DIVIDE IT THE SAME WAY, and
    # on a real plan they never do. Matching whole edges caught the easy case
    # — two rooms exactly back to back — and missed every partition that a
    # different number of rooms lands on from each side. On a four-bed with a
    # hall one side of a line and a garage plus a study the other, 32.0m of
    # the 91.5m of partition was built TWICE: the whole first-floor spine and
    # the whole garage wall, both duplicated, and with them 17 phantom
    # doorsets on partitions that already had a door. wall_length_m came back
    # 23.6% high.
    #
    # So cut every collinear run at the boundaries coming from BOTH sides and
    # build each atomic piece once. Two rooms flush back to back still give
    # one wall, exactly as before.
    edges = {}
    for room in rooms:
        rx0, ry0 = room.x, room.y
        rx1, ry1 = room.x + room.width, room.y + room.depth
        for key, lo, hi in (
                (("x", round(rx0, 3)), ry0, ry1),
                (("x", round(rx1, 3)), ry0, ry1),
                (("y", round(ry0, 3)), rx0, rx1),
                (("y", round(ry1, 3)), rx0, rx1)):
            edges.setdefault(key, []).append((lo, hi, room))

    walls = []
    for (axis, coord), claims in sorted(edges.items()):
        cuts = sorted({round(v, 3) for lo, hi, _ in claims for v in (lo, hi)})
        for lo, hi in zip(cuts, cuts[1:]):
            if hi - lo < 1e-6:
                continue
            mid = (lo + hi) / 2.0
            here = [r for a, b, r in claims if a - 1e-6 <= mid <= b + 1e-6]
            if not here:
                continue
            start = (coord, lo) if axis == "x" else (lo, coord)
            end = (coord, hi) if axis == "x" else (hi, coord)
            wall = Wall(start, end, internal,
                        max(r.height for r in here), external=True)
            # THE WALL IS AS TALL AS EVERY ROOM THAT CLAIMS IT. A storey
            # built over another block shares all four of its edges with the
            # block below; taking only the first claim left the new floor as
            # a roof over open air, with daylight through the front wall.
            wall.base_level = min(r.base_level for r in here)
            if any(r.storeys is None for r in here):
                wall.storeys = None           # a room on every storey wins
            else:
                wall.storeys = max(r.base_level + r.storeys
                                   for r in here) - wall.base_level
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
        both, inside_signs, sides = 0, [], []
        for sign in (1, -1):
            px, py = mx + nx * step * sign, my + ny * step * sign
            hits = [r for r in rooms
                    if r.x - 1e-6 <= px <= r.x + r.width + 1e-6
                    and r.y - 1e-6 <= py <= r.y + r.depth + 1e-6]
            if hits:
                both += 1
                inside_signs.append(sign)
                sides.append(hits)
        wall.external = both < 2
        # Exactly one side landed in a room, so the other side is the street.
        if len(inside_signs) == 1:
            wall.outward = -inside_signs[0]
            wall.outward_hint = -inside_signs[0]
        # A WALL CAN BE INTERNAL LOW DOWN AND EXTERNAL HIGHER UP.
        #
        # Where a single-storey extension abuts a two-storey house, the wall
        # between them has a room on both sides at ground floor and open sky
        # on one side above the extension's roof. Held as one boolean it came
        # out plastered for its whole height, which put bare plasterwork on
        # the outside of the house above every rear extension this models.
        # Shared only as far up as the SHALLOWER of the two blocks goes.
        if both == 2:
            depth_levels = []
            for hits in sides:
                lv = [(r.storeys if r.storeys is not None else 10**6)
                      for r in hits]
                depth_levels.append(max(lv))
            wall.shared_storeys = min(depth_levels)
            # ...and above that level, "outside" is over the SHALLOWER block,
            # so that is the way the brick face has to point. Left unset the
            # outward default put the brickwork indoors and showed the
            # plaster to the garden.
            if depth_levels[0] != depth_levels[1]:
                shallow = 0 if depth_levels[0] < depth_levels[1] else 1
                wall.outward = inside_signs[shallow]

    # A WALL CAN BE "EXTERNAL" AND STILL FACE INDOORS. Real plans are not
    # flush: two rooms drawn 100mm apart leave a void strip between them, and
    # the probe correctly reports "no room on the other side" — but that
    # other side is a cavity inside the building, not the street. Treating it
    # as street put a WINDOW on it, glazing a view of the neighbouring
    # wall's face 100mm away. Seen literally, in a walkthrough: glass with
    # brickwork pressed against it.
    #
    # The tell is cheap: if the outside probe point still lands inside the
    # plan's own bounding box, the wall faces a void, not the sky.
    if rooms:
        ex0 = min(r.x for r in rooms); ex1 = max(r.x + r.width for r in rooms)
        ey0 = min(r.y for r in rooms); ey1 = max(r.y + r.depth for r in rooms)
    for wall in walls:
        wall.void_facing = False
        if not wall.external or not rooms:
            continue
        (ax, ay), (bx, by) = wall.start, wall.end
        length = wall.length_m
        if length <= 0:
            continue
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        nx, ny = -(by - ay) / length, (bx - ax) / length
        step = max(internal, external) + 0.05
        for sign in (1, -1):
            px, py = mx + nx * step * sign, my + ny * step * sign
            in_room = any(r.x - 1e-6 <= px <= r.x + r.width + 1e-6
                          and r.y - 1e-6 <= py <= r.y + r.depth + 1e-6
                          for r in rooms)
            if not in_room:
                wall.void_facing = (ex0 + 1e-6 < px < ex1 - 1e-6
                                    and ey0 + 1e-6 < py < ey1 - 1e-6)
                break

    # PUT THE PIECES BACK TOGETHER WHERE THEY ARE ONE WALL. Cutting every
    # collinear run at the boundaries from both sides is what stops a
    # partition being built twice — but it also split the FRONT of the house
    # at the first-floor bathroom partition, because that partition's line
    # crosses the external wall plane. The facade then had no single wall
    # wide enough to take the front door, and the door was silently dropped.
    # Adjacent pieces that agree on every property are one wall again; the
    # probes above have already run, so nothing that differs gets merged.
    walls.sort(key=lambda w: (w.start[0] == w.end[0],
                              round(w.start[0] if w.start[0] == w.end[0]
                                    else w.start[1], 3),
                              min(w.start[1], w.end[1]) if w.start[0] == w.end[0]
                              else min(w.start[0], w.end[0])))
    merged = []
    for wall in walls:
        prev = merged[-1] if merged else None
        if prev is not None and _joinable(prev, wall):
            prev.end = wall.end
            merged[-1] = prev
            continue
        merged.append(wall)
    walls = merged

    for wall in walls:
        wall.thickness = external if wall.external else internal
    return walls


def _joinable(a, b):
    """Are two collinear neighbours the same wall, cut in two?"""
    vertical = a.start[0] == a.end[0] and b.start[0] == b.end[0]
    horizontal = a.start[1] == a.end[1] and b.start[1] == b.end[1]
    if vertical:
        if abs(a.start[0] - b.start[0]) > 1e-6 or abs(a.end[1] - b.start[1]) > 1e-6:
            return False
    elif horizontal:
        if abs(a.start[1] - b.start[1]) > 1e-6 or abs(a.end[0] - b.start[0]) > 1e-6:
            return False
    else:
        return False
    return (a.external == b.external
            and a.base_level == b.base_level
            and a.storeys == b.storeys
            and abs(a.height - b.height) < 1e-6
            and getattr(a, "outward", 1) == getattr(b, "outward", 1)
            and getattr(a, "shared_storeys", None) == getattr(b, "shared_storeys", None)
            and getattr(a, "void_facing", False) == getattr(b, "void_facing", False))


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
              max_span=MAX_ROOF_SPAN_M, ridge_along=None):
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
    # The ridge runs along the LONGER axis by default; the slope climbs
    # across the shorter one. That default is right for most plans and WRONG
    # for a narrow-fronted house, which a real section sheet demonstrated:
    # a 5.4m-front, 8.9m-deep terrace type ridges along its 5.4m frontage,
    # spanning the full 8.9m depth — the exact opposite of longest-axis.
    # `ridge_along` ("x" or "y") lets the caller state what the drawing
    # shows instead of accepting the guess.
    if ridge_along is None:
        along_x = width >= depth
    elif ridge_along in ("x", "y"):
        along_x = ridge_along == "x"
    else:
        raise ModelError("ridge_along must be 'x' or 'y' when given")
    total_span = depth if along_x else width
    run = width if along_x else depth          # length of a ridge, gable end
    n_ranges = max(1, int(math.ceil(total_span / max_span - 1e-9)))
    span = total_span / n_ranges
    # A RAFTER BEARS ON THE WALL PLATE; THE OVERHANG PROJECTS OUT AND DOWN
    # PAST IT. Taking the rise off the overhung span raised the ridge by
    # overhang x tan(pitch) — 210mm here — and ridge height is the number a
    # planning condition is written against. The rise is measured across the
    # structural span; the eaves TIP then sits below the plate by the same
    # geometry, which keeps every plane at the stated pitch.
    struct_span = max(1e-6, span - 2.0 * overhang / n_ranges)
    rise = (struct_span / 2.0) * math.tan(theta)
    ridge_z = base_z + rise
    eaves_tip_z = base_z - overhang * math.tan(theta)

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
        # A GABLE HAS EAVES ON TWO SIDES ONLY. The other two carry verge —
        # no gutter, no fascia, no soffit. Reporting the whole perimeter as
        # eaves counted the verge twice, once on each line of the quote, and
        # over-measured guttering by 82%.
        "eaves_m": round(2 * run if kind == "gabled"
                         else 2 * (width + depth), 2),
        # ...and a verge is a RAKING edge. Measuring it flat on plan
        # under-ordered dry-verge and barge by the same 1/cos(pitch) this
        # module lectures about three paragraphs above.
        "verge_m": (round(2 * total_span / math.cos(theta), 2)
                    if kind == "gabled" else 0.0),
        "eaves_tip_z_m": round(eaves_tip_z, 3),
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
          storey_height=None, roof=None, front_door=True, party_edges=None):
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

    # A ROOM ABOVE THE ROOF IS A CONTRADICTION, NOT A ROOM. base_level at or
    # past the building's storey count left the room in the schedule but in
    # no wall, no floor total and no export — it silently vanished, which is
    # worse than either building it or refusing it. Refuse, with the fix.
    for r in rooms:
        if r.base_level >= storeys:
            raise ModelError(
                f"{r.name}: base_level {r.base_level} puts the room at or "
                f"above the building's top — the model has {storeys} "
                f"storey(s), so levels run 0 to {storeys - 1}. Raise "
                f"plan.storeys or lower the room.")

    walls = walls_from_rooms(rooms)

    # A PARTY WALL IS THE NEIGHBOUR'S HOUSE, NOT THE SKY. On a semi or a
    # terrace the probe finds no room beyond the shared line and calls it
    # external — which put rule windows through next door's living room and
    # would cost the whole line as heat-loss brickwork. The caller states
    # which boundary lines are shared: [["x", 0.0], ["y", 8.5]].
    for axis, coord in (party_edges or []):
        for wall in walls:
            (ax, ay), (bx, by) = wall.start, wall.end
            on = (abs(ax - coord) < 1e-6 and abs(bx - coord) < 1e-6) \
                if axis == "x" else \
                (abs(ay - coord) < 1e-6 and abs(by - coord) < 1e-6)
            if on and wall.external:
                wall.party = True

    if wall_openings:
        for wall in walls:
            if getattr(wall, "void_facing", False):
                # No window onto a 100mm cavity, and no door into it either.
                continue
            if getattr(wall, "party", False):
                # And none through the neighbour's lounge.
                continue
            if wall.external and wall.length_m >= 1.8:
                # ONE WINDOW PER ROOM, NOT PER WALL. A single window in the
                # middle of a wall was fine while every room edge was its own
                # wall — but a 10.5m frontage is ONE wall, and one window in
                # the middle of it left the bedrooms at either end with no
                # daylight and, worse, no escape opening. Space them at
                # roughly a room's width instead.
                n = max(1, int(round(wall.length_m / WINDOW_PITCH_M)))
                bay = wall.length_m / n
                for i in range(n):
                    wall.add_opening("window", i * bay + (bay - 1.2) / 2.0,
                                     1.2, WINDOW_H_M, WINDOW_SILL_M)
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

    # A dwelling has a front door, and the first render of a real house
    # type came back without one: the auto-openings put windows on external
    # walls and doors on internal ones, and no rule ever said "someone has
    # to be able to get in". The front is the y0 edge — the elevation a plan
    # is conventionally drawn facing — and the door goes on its longest
    # external wall, on the GROUND FLOOR ONLY (level=0): walls repeat per
    # storey, so an unpinned door would float on every upper floor.
    if wall_openings and front_door:
        fronts = [w for w in walls if w.external
                  and abs(w.start[1] - y0) < 1e-6
                  and abs(w.end[1] - y0) < 1e-6]
        if fronts:
            dw = max(fronts, key=lambda w: w.length_m)
            taken = [(o["along"], o["along"] + o["width"])
                     for o in dw.openings]
            a, placed = 0.25, False
            while a + DOOR_W_M + 0.25 <= dw.length_m:
                if all(a + DOOR_W_M <= s - 0.1 or a >= e + 0.1
                       for s, e in taken):
                    dw.add_opening("door", a, DOOR_W_M, DOOR_H_M, level=0)
                    placed = True
                    break
                a += 0.1
            if not placed and dw.length_m >= DOOR_W_M + 0.2:
                # A short front wall whose window leaves no room: the door
                # matters more than the window it displaces.
                dw.openings.clear()
                dw.add_opening("door", (dw.length_m - DOOR_W_M) / 2,
                               DOOR_W_M, DOOR_H_M, level=0)
    # The eaves sit on TOP OF THE TOPMOST WALL, not a floor zone above it.
    # `per_storey * storeys` reads naturally and is wrong by exactly one
    # floor zone: it leaves the roof floating 350mm clear of the walls it is
    # supposed to be bearing on, which is a visible hole in the model and a
    # wall plate nailed to fresh air.
    eaves_z = per_storey * (storeys - 1) + height

    roof_model = None
    if roof:
        # The validator stores "not stated" as an explicit None — the key is
        # PRESENT, so dict.get(key, default) never falls back, and None
        # reached roof_over's arithmetic. Live-confirmed on the deployed
        # worker: {"roof": {"pitch_deg": 35}} crashed the whole job with
        # `float - NoneType` because overhang_m arrived as None. Every local
        # test hand-built its roof dict with all keys set, so the shape the
        # validator actually produces had never once been fed through here.
        def _given(key, default):
            v = roof.get(key)
            return default if v is None else v
        roof_model = roof_over(
            x0, y0, x1, y1,
            pitch_deg=_given("pitch_deg", DEFAULT_PITCH_DEG),
            kind=_given("kind", "hipped"),
            # ACCEPT THE KEY PEOPLE WRITE. The spec says "overhang" and
            # this read "overhang_m", so a stated 350mm eaves was dropped on
            # the floor without a word and 300 used instead — a 2.5 m2 error
            # in the tile order, from a typo the caller could never see.
            overhang=_given("overhang_m",
                            _given("overhang", DEFAULT_EAVES_OVERHANG_M)),
            base_z=eaves_z,
            ridge_along=_given("ridge_along", None),
            # The default cap exists to stop a whole-building footprint
            # being roofed in one impossible span. When the section shows
            # one clear span — as a 9.1m trussed roof on a real sheet did —
            # the caller states it and the drawing wins over the heuristic.
            max_span=_given("max_span_m", MAX_ROOF_SPAN_M))

    # A BLOCK THAT STOPS SHORT OF THE MAIN ROOF NEEDS ITS OWN TOP.
    # The main roof spans the whole plan at eaves level, so a single-storey
    # rear extension on a two-storey house is left as an open box: walls up
    # to 2.4m and the sky above them. First render of one showed straight
    # down into it. Flat is right for the overwhelming majority of
    # single-storey rear extensions in this country.
    def _covered_above(r, level):
        """Is another room built directly on top of this block?"""
        for o in rooms:
            if o is r:
                continue
            top = storeys if o.storeys is None else o.base_level + o.storeys
            if not (o.base_level <= level < top):
                continue
            ox = min(r.x + r.width, o.x + o.width) - max(r.x, o.x)
            oy = min(r.y + r.depth, o.y + o.depth) - max(r.y, o.y)
            if ox > 0.05 and oy > 0.05:
                return True
        return False

    caps = []
    for r in rooms:
        if r.storeys is None or r.base_level + r.storeys >= storeys:
            continue
        # A CAP IS FOR A BLOCK WITH SKY OVER IT, NOT A CEILING. Every
        # ground-floor room of a two-storey house is "short of the top", so
        # capping on that test alone tiled a flat roof over the lounge with
        # a bedroom standing on it — a roof plane inside the building, in
        # the take-off and in the IFC. Only cap what nothing is built on.
        if _covered_above(r, r.base_level + r.storeys):
            continue
        cap_z = per_storey * (r.base_level + r.storeys - 1) + r.height
        caps.append({"x": [round(r.x, 3), round(r.x + r.width, 3)],
                     "y": [round(r.y, 3), round(r.y + r.depth, 3)],
                     "z_m": round(cap_z, 3), "kind": "flat"})

    top = roof_model["ridge_z_m"] if roof_model else eaves_z

    # Openings pinned to one level count ONCE, not once per storey — the
    # front door is on the ground floor, and multiplying it up put a phantom
    # door (and its missing wall area) on every floor of the take-off.
    def _levels(w):
        base = getattr(w, "base_level", 0)
        if w.storeys is None:
            return max(0, storeys - base)
        return max(0, min(base + w.storeys, storeys) - base)

    def _count(kind):
        return sum(_levels(w) if o["level"] is None else 1
                   for w in walls for o in w.openings if o["kind"] == kind)

    # A ROOM ALSO KNOWS WHICH STOREYS IT IS ON. Multiplying the room count
    # and the floor area by `storeys` is right only for the original case —
    # one plate repeated all the way up. Give build() a real first-floor plan
    # (base_level=1) and it counted every room on every storey: a 178.5 m2
    # four-bed came back as 357.0 m2, double, on the one number a builder
    # prices from. Where every room is the old shape (storeys=None,
    # base_level=0) this is arithmetically identical to what it replaced.
    def _room_levels(r):
        if r.storeys is None:
            return max(0, storeys - r.base_level)
        return max(0, min(r.base_level + r.storeys, storeys) - r.base_level)

    room_levels = sum(_room_levels(r) for r in rooms)
    wall_levels = sum(_levels(w) for w in walls)
    single_plate = all(r.storeys is None and r.base_level == 0 for r in rooms)

    gross_wall = sum(w.length_m * w.height * _levels(w) for w in walls)
    cut = sum((o["width"] * o["height"])
              * (_levels(w) if o["level"] is None else 1)
              for w in walls for o in w.openings)

    result = {
        "rooms": [r.as_dict() for r in rooms],
        "walls": [w.as_dict() for w in walls],
        "storeys": storeys,
        "storey_height_m": round(per_storey, 3),
        "eaves_z_m": round(eaves_z, 3),
        "caps": caps,
        "roof": roof_model,
        "roof_quantities": roof_quantities(roof_model) if roof_model else None,
        "extent_m": {"x": [round(x0, 3), round(x1, 3)],
                     "y": [round(y0, 3), round(y1, 3)],
                     "z": [0.0, round(top, 3)]},
        "totals": {
            "storeys": storeys,
            "rooms": room_levels,
            "floor_area_m2": round(
                sum(r.area_m2 * _room_levels(r) for r in rooms), 2),
            "walls": wall_levels,
            "wall_length_m": round(
                sum(w.length_m * _levels(w) for w in walls), 2),
            "wall_area_net_m2": round(max(0.0, gross_wall - cut), 2),
            "doors": _count("door"),
            "windows": _count("window"),
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
    if storeys > 1 and single_plate:
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
            if not _wall_on_level(w, level):
                continue
            (ax, ay), (bx, by) = w["start"], w["end"]
            t = w["thickness_m"] / 2.0
            if abs(bx - ax) >= abs(by - ay):        # runs along x
                lo, hi = sorted((ax, bx))
                for j, (s, e, zlo, zhi) in enumerate(
                        _split_for_openings(lo, hi, w, level)):
                    box(s, ay - t, z + zlo, e, ay + t, z + zhi,
                        f"L{level}_wall_{i}_{j}")
            else:                                   # runs along y
                lo, hi = sorted((ay, by))
                for j, (s, e, zlo, zhi) in enumerate(
                        _split_for_openings(lo, hi, w, level)):
                    box(ax - t, s, z + zlo, ax + t, e, z + zhi,
                        f"L{level}_wall_{i}_{j}")

    for n, cap in enumerate(model.get("caps") or []):
        cx, cy, cz = cap["x"], cap["y"], cap["z_m"]
        box(cx[0], cy[0], cz - DEFAULT_SLAB_M, cx[1], cy[1], cz, f"cap_{n}")

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
    ez = roof.get("eaves_tip_z_m", roof["eaves_z_m"])
    rz = roof["ridge_z_m"]
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


def _openings_at(wall, level):
    """The openings that exist on THIS storey: unpinned ones repeat with
    the plate; a level-pinned one (the front door) appears once."""
    return [o for o in wall["openings"]
            if o.get("level") is None or o.get("level") == level]


def _split_for_openings(lo, hi, wall, level=0):
    """A wall with a hole in it is several boxes, not one.

    Returns [(from, to, z_low, z_high)]. Above a door there is still a
    lintel; above a window there is a lintel and below it a spandrel, and
    leaving either out is how a model ends up with daylight through the
    brickwork.
    """
    h = wall["height_m"]
    ops = _openings_at(wall, level)
    if not ops:
        return [(lo, hi, 0.0, h)]
    out, cursor = [], lo
    for o in sorted(ops, key=lambda o: o["along"]):
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
    """IFC4 with the WHOLE building in it, not a husk of it.

    An independent audit executed the previous version and found what it
    actually wrote: seven walls and four spaces on ONE storey at z=0 — no
    slabs, no roof, no doors, no windows, no openings, no upper floors —
    while the GLB from the same model carried all of them. That IFC could
    not support this product's own pricing story ("IfcOpeningElement",
    "IfcSlab", IFC-native takeoff), and "exports real CAD" was an
    overstatement. This version writes what the model holds:

      IfcBuildingStorey  one per storey, at its real elevation
      IfcWall            per storey it exists on, placed at that storey's z
      IfcOpeningElement  every door and window, voiding its wall
      IfcDoor/IfcWindow  filling those openings
      IfcSlab FLOOR      the floor plate of every storey
      IfcSlab ROOF       the flat cap over any lower block
      IfcRoof            the pitched roof, as the same surfaces the GLB has
      IfcSpace           each room, aggregated into its base storey
    """
    try:
        import ifcopenshell
        import ifcopenshell.api.root
        import ifcopenshell.api.project
        import ifcopenshell.api.unit
        import ifcopenshell.api.context
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.spatial
        import ifcopenshell.api.geometry
        import ifcopenshell.api.feature
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
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)

    storeys_n = model.get("storeys", 1)
    per = model.get("storey_height_m", DEFAULT_CEILING_HEIGHT_M)
    x0, x1 = model["extent_m"]["x"]
    y0, y1 = model["extent_m"]["y"]

    def box_at(el, wx, wy, wz, ux, uy, ldim, tdim, ddim):
        """A swept solid ldim x tdim extruded up ddim, at a world placement
        whose local x runs along (ux, uy)."""
        run("geometry.edit_object_placement", f, product=el, matrix=(
            (ux, -uy, 0.0, wx), (uy, ux, 0.0, wy),
            (0.0, 0.0, 1.0, wz), (0.0, 0.0, 0.0, 1.0)))
        profile = f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA",
            XDim=float(ldim), YDim=float(tdim),
            Position=f.create_entity("IfcAxis2Placement2D",
                Location=f.create_entity("IfcCartesianPoint",
                                         Coordinates=(ldim / 2.0, 0.0))))
        solid = f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile,
            Position=f.create_entity("IfcAxis2Placement3D",
                Location=f.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0))),
            ExtrudedDirection=f.create_entity("IfcDirection",
                                              DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(ddim))
        shape = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=body,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid",
            Items=[solid])
        run("geometry.assign_representation", f, product=el,
            representation=shape)

    storeys = []
    names = {0: "Ground Floor", 1: "First Floor", 2: "Second Floor"}
    for level in range(storeys_n):
        st = run("root.create_entity", f, ifc_class="IfcBuildingStorey",
                 name=names.get(level, f"Storey {level}"))
        st.Elevation = round(level * per, 3)
        run("aggregate.assign_object", f, products=[st],
            relating_object=building)
        storeys.append(st)

    for level, st in enumerate(storeys):
        z = level * per

        # The floor plate. Extruded downward-thick so its top is the FFL.
        slab = run("root.create_entity", f, ifc_class="IfcSlab",
                   name=f"Floor slab L{level}", predefined_type="FLOOR")
        run("spatial.assign_container", f, products=[slab],
            relating_structure=st)
        box_at(slab, x0, y0, z - DEFAULT_SLAB_M, 1.0, 0.0,
               x1 - x0, (y1 - y0), DEFAULT_SLAB_M)

        for i, w in enumerate(model["walls"]):
            if not _wall_on_level(w, level):
                continue
            (ax, ay), (bx, by) = w["start"], w["end"]
            length = w["length_m"]
            if length <= 0:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            el = run("root.create_entity", f, ifc_class="IfcWall",
                     name=f"Wall {i} L{level} {length:.2f}m")
            run("spatial.assign_container", f, products=[el],
                relating_structure=st)
            box_at(el, ax, ay, z, ux, uy,
                   length, w["thickness_m"], w["height_m"])

            # Openings: voided out of the wall, then filled with the door
            # or window. Pinned openings appear on their own level only.
            for o in w.get("openings", []):
                if o.get("level") is not None and o["level"] != level:
                    continue
                sill = 0.0 if o["kind"] == "door" else o.get("sill", 0.0)
                op = run("root.create_entity", f,
                         ifc_class="IfcOpeningElement",
                         name=f"Opening {o['kind']} in wall {i} L{level}")
                box_at(op, ax + ux * o["along"], ay + uy * o["along"],
                       z + sill, ux, uy,
                       o["width"], w["thickness_m"] * 1.2, o["height"])
                run("feature.add_feature", f, feature=op, element=el)
                fill_class = "IfcDoor" if o["kind"] == "door" else "IfcWindow"
                fill = run("root.create_entity", f, ifc_class=fill_class,
                           name=f"{o['kind']} in wall {i} L{level}")
                run("spatial.assign_container", f, products=[fill],
                    relating_structure=st)
                box_at(fill, ax + ux * o["along"], ay + uy * o["along"],
                       z + sill, ux, uy,
                       o["width"], min(w["thickness_m"], 0.06), o["height"])
                run("feature.add_filling", f, opening=op, element=fill)

    # Flat caps over the shallower blocks, on the storey below their top.
    for n, cap in enumerate(model.get("caps") or []):
        cx, cy, cz = cap["x"], cap["y"], cap["z_m"]
        level = min(max(int(cz / per) - (1 if cz % per < 0.01 else 0), 0),
                    storeys_n - 1)
        slab = run("root.create_entity", f, ifc_class="IfcSlab",
                   name=f"Flat roof {n}", predefined_type="ROOF")
        run("spatial.assign_container", f, products=[slab],
            relating_structure=storeys[level])
        box_at(slab, cx[0], cy[0], cz, 1.0, 0.0,
               cx[1] - cx[0], cy[1] - cy[0], DEFAULT_SLAB_M)

    # The pitched roof: the SAME surfaces the GLB carries, as a face-based
    # surface model under an IfcRoof — honest geometry rather than a shape
    # approximated a second time and free to drift from the mesh.
    roof = model.get("roof")
    if roof:
        groups = _glb_mesh(model)
        tris = groups.get("tile")
        if tris:
            pos, _, idx = tris
            faces = []
            for i in range(0, len(idx), 3):
                loop = f.create_entity("IfcPolyLoop", Polygon=[
                    f.create_entity("IfcCartesianPoint", Coordinates=(
                        float(pos[3 * idx[i + k]]),
                        float(-pos[3 * idx[i + k] + 2]),
                        float(pos[3 * idx[i + k] + 1])))
                    for k in range(3)])
                faces.append(f.create_entity("IfcFace", Bounds=[
                    f.create_entity("IfcFaceOuterBound", Bound=loop,
                                    Orientation=True)]))
            surf = f.create_entity("IfcFaceBasedSurfaceModel",
                                   FbsmFaces=[f.create_entity(
                                       "IfcConnectedFaceSet", CfsFaces=faces)])
            el = run("root.create_entity", f, ifc_class="IfcRoof",
                     name=f"Roof {roof.get('kind', '')} "
                          f"{roof.get('pitch_deg', '')} deg")
            run("spatial.assign_container", f, products=[el],
                relating_structure=storeys[-1])
            shape = f.create_entity(
                "IfcShapeRepresentation", ContextOfItems=body,
                RepresentationIdentifier="Body",
                RepresentationType="SurfaceModel", Items=[surf])
            run("geometry.assign_representation", f, product=el,
                representation=shape)

    for room in model["rooms"]:
        space = run("root.create_entity", f, ifc_class="IfcSpace",
                    name=room["name"])
        # IfcSpace is a spatial STRUCTURE element: it is AGGREGATED into the
        # storey, not contained in it. assign_container raises here.
        base = min(int(room.get("base_level") or 0), storeys_n - 1)
        run("aggregate.assign_object", f, products=[space],
            relating_object=storeys[base])

    f.write(path)
    return path


# --- handler entry point ----------------------------------------------------

def _with_buildability(model):
    """Never hand over a plan without saying whether it can be built.

    The model is geometry and the geometry always closes; whether a person
    can get up the stairs is a separate question, and it was never being
    asked. A four-bed went out of here complete — roof, elevations, IFC,
    take-off — with no staircase that could reach the first floor. The
    answer rides alongside the model from here on, and its refusals are
    promoted into the warnings so they cannot be missed by a caller that
    only reads those.
    """
    out = {"model": model, "warnings": list(model["warnings"])}
    try:
        import buildable
    except ImportError:                     # pragma: no cover - optional
        return out
    result = buildable.check(model)
    out["buildable"] = result
    for f in result["findings"]:
        if f["severity"] == "refuse":
            out["warnings"].append("NOT BUILDABLE: " + f["message"])

    # Heating and ventilation ride along with buildability: the design
    # heat loss is computed from the same measured walls and openings the
    # geometry carries, and Part F rates from the same room schedule — so
    # a model never ships without its radiators and its fans.
    try:
        import heatloss
        out["heat"] = heatloss.design(model)
    except ImportError:                     # pragma: no cover - optional
        pass
    try:
        import ventilation
        out["vent"] = ventilation.design(model)
    except ImportError:                     # pragma: no cover - optional
        pass
    try:
        import electrics
        out["elec"] = electrics.design(model, heat=out.get("heat"))
    except ImportError:                     # pragma: no cover - optional
        pass

    # Every pipe and wire ROUTED, not estimated — needs the heating,
    # electrical and ventilation designs above it.
    try:
        import mep as _mep
        out["mep"] = _mep.design(model, heat=out.get("heat"),
                                 elec=out.get("elec"), vent=out.get("vent"))
    except ImportError:                     # pragma: no cover - optional
        pass

    # The bill of quantities counts what the services designs
    # specified, so it runs LAST of the design passes.
    try:
        import quantities as _q
        out["quantities_bill"] = _q.bill(model, heat=out.get("heat"),
                                         elec=out.get("elec"),
                                         mep=out.get("mep"))
    except ImportError:                     # pragma: no cover - optional
        pass

    # THE RULES ENGINE FINALLY RUNS. regs.py has carried measured Part K,
    # B1 and F limits since it was written and was imported by nothing but
    # its own tests — the pipeline's "compliance findings" silently excluded
    # every one. The stair the fitter just designed is judged by the rules
    # engine's own arithmetic, and every habitable room gets the 1/20 purge
    # check from the openings the model actually carries.
    try:
        import regs
    except ImportError:                     # pragma: no cover - optional
        return out
    findings = []
    stair = result.get("stair")
    if stair and stair.get("rise_m") and stair.get("going_m"):
        findings += regs.check_stair(stair["rise_m"], stair["going_m"],
                                     uncertainty=0.0,
                                     location=stair.get("in_room"))
    storeys = model.get("storeys", 1)
    for room in model["rooms"]:
        if room.get("kind") not in buildable.HABITABLE:
            continue
        base = room.get("base_level") or 0
        span = room.get("storeys")
        top = storeys if span is None else base + int(span)
        for level in range(base, top):
            openable = sum(
                o["width"] * o["height"]
                for o in buildable._openings_of(model, room, level)
                if o["kind"] == "window")
            findings += regs.check_purge_ventilation(
                openable, room["area_m2"],
                location=f"{room['name']} L{level}")
    summary = regs.summarise(findings)
    out["regs"] = summary
    for item in summary["critical"]:
        if item.get("verdict") == "fail":
            out["warnings"].append("REGS FAIL: " + item["message"])
    return out


def _absorb_buildability(model, extra):
    """Fold the check's outcome INTO the model before anything exports it.

    The stair becomes part of the geometry record — a floor plan cannot be
    drawn from a model that does not know where its staircase is — and the
    promoted warnings travel in the model's own warning list, so a JSON
    consumer sees exactly what the API caller sees.
    """
    result = extra.get("buildable")
    if not result:
        return
    if result.get("stair"):
        model["stair"] = result["stair"]
    model["buildable"] = {"buildable": result["buildable"],
                          "counts": result["counts"],
                          "findings": result["findings"]}
    if extra.get("regs"):
        model["regs"] = extra["regs"]
    if extra.get("heat"):
        model["heat"] = extra["heat"]
    if extra.get("vent"):
        model["vent"] = extra["vent"]
    if extra.get("elec"):
        model["elec"] = extra["elec"]
    if extra.get("mep"):
        model["mep"] = extra["mep"]
    if extra.get("quantities_bill"):
        model["quantities_bill"] = extra["quantities_bill"]
    model["warnings"] = list(extra["warnings"])


def run_mode(spec, prog, output_dir):
    """Model mode entry point.

    Two ways in, one model out: a plan typed off a drawing's figured
    dimensions, or an Apple RoomPlan scan (roomplan_url / roomplan_path).
    The scan wins when both are absent-vs-present is unambiguous; when a
    caller sends BOTH, the plan is used and the scan noted, because typed
    dimensions were deliberate and a stale scan URL riding along in a
    re-used job body should not silently replace them.
    """
    import paths

    prog.stage("reading")
    plan = spec.get("plan") or {}
    entries = plan.get("rooms") or spec.get("rooms")
    scan_src = spec.get("roomplan_url") or spec.get("roomplan_path")

    if not entries and scan_src:
        import roomplan
        directory = paths.ensure(output_dir)
        local = roomplan.fetch_export(spec, directory)
        prog.stage("building")
        model = roomplan.to_model(roomplan.parse(local))
        extra = _with_buildability(model)
        _absorb_buildability(model, extra)
        prog.stage("exporting")
        artifacts = _export_artifacts(
            model, directory, spec.get("scan_id") or "roomplan")
        return artifacts, extra

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
            kind=e.get("kind", "room"),
            # None means "every storey", exactly as Room defines it — the
            # two fields the whole per-level machinery hangs off, and the
            # two this constructor was silently discarding.
            storeys=e.get("storeys"),
            base_level=int(e.get("base_level") or 0)))

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
                  roof=plan.get("roof"),
                  front_door=plan.get("front_door", True),
                  party_edges=plan.get("party_walls"))

    if sched_note:
        model["warnings"].append(sched_note)
    if scan_src:
        model["warnings"].append(
            "Both a typed plan and a RoomPlan scan were supplied. The typed "
            "plan was used — deliberate dimensions beat a scan URL riding "
            "along in a re-used job body. Send the scan without a plan to "
            "model from it.")

    # THE CHECK RUNS BEFORE THE EXPORT, AND THE STAIR GOES INTO THE MODEL.
    # The other way round, the fitted flight existed only in the returned
    # wrapper: every exported file — the JSON a floor plan would be drawn
    # from included — described a house with no staircase in it.
    extra = _with_buildability(model)
    _absorb_buildability(model, extra)

    prog.stage("exporting")
    directory = paths.ensure(output_dir)
    artifacts = _export_artifacts(model, directory,
                                  spec.get("scan_id") or "model")
    return artifacts, extra


def _export_artifacts(model, directory, scan):
    """OBJ, GLB, IFC and JSON for a finished model dict.

    Shared by the plan path and the RoomPlan path — the writers do not care
    where a model came from, and having two copies of this block is how the
    two paths drift apart one bugfix at a time.
    """
    artifacts = []

    obj_path = os.path.join(directory, f"{scan}.obj")
    write_obj(model, obj_path)
    artifacts.append((obj_path, f"models/{scan}.obj", None))
    model["obj"] = True

    # GLB is the one an app can actually show. An OBJ needs a viewer that
    # understands .mtl and carries no materials on its own; a GLB is a single
    # file with PBR materials that opens in a browser, in QuickLook on an
    # iPhone, and in every 3D tool. Same failure policy as IFC: a broken
    # export must not take down the quantities, which are the point.
    glb_path = os.path.join(directory, f"{scan}.glb")
    try:
        write_glb(model, glb_path)
        artifacts.append((glb_path, f"models/{scan}.glb", None))
        model["glb"] = True
    except Exception as e:
        model["glb"] = False
        model["warnings"].append(
            f"GLB export failed ({type(e).__name__}: {e}). The OBJ and every "
            f"quantity above are unaffected.")

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

    return artifacts


run = run_mode


# --- glTF binary ------------------------------------------------------------
#
# WHY NOT BLENDER. GLB is the right thing to hand an app: one file, PBR
# materials, opens in a browser, in QuickLook on an iPhone and in every
# viewer there is. Blender is not needed to produce one — a GLB is a 12-byte
# header, a JSON chunk and a binary chunk, and writing it here keeps the
# image small and the tests dependency-free, exactly as write_obj and
# write_ifc already are. Adding Blender would put ~1GB and a headless render
# stack into the worker to do a serialisation job the standard library can
# do. What Blender would genuinely buy — baked lighting and ambient
# occlusion — belongs in a render step, not in the geometry export.

GLB_MATERIALS = [
    # name,          base colour RGBA,             metallic, roughness
    ("brick",        (0.62, 0.37, 0.27, 1.0),      0.0, 0.95),
    ("plaster",      (0.87, 0.85, 0.82, 1.0),      0.0, 0.90),
    ("tile",         (0.29, 0.26, 0.24, 1.0),      0.0, 0.85),
    ("glass",        (0.44, 0.62, 0.72, 0.45),     0.0, 0.10),
    ("door",         (0.56, 0.42, 0.29, 1.0),      0.0, 0.60),
    ("floor",        (0.72, 0.52, 0.29, 1.0),      0.0, 0.70),
    ("slab",         (0.78, 0.77, 0.75, 1.0),      0.0, 0.90),
]
_GLB_INDEX = {name: i for i, (name, *_) in enumerate(GLB_MATERIALS)}


def _glb_mesh(model):
    """Triangles per material, in glTF's Y-up axes.

    Returns {material_name: (positions, normals, indices)}. Positions are
    flat lists of floats; the plan's Y runs into -Z, matching write_obj so
    the two exports describe the same building rather than two mirror
    images of it.
    """
    out = {}

    def emit(mat, quad):
        pos, nrm, idx = out.setdefault(mat, ([], [], []))
        a, b, c, d = [(p[0], p[2], -p[1]) for p in quad]
        # A ROOF END IS A TRIANGLE, WRITTEN AS A QUAD WITH TWO VERTICES ON
        # THE APEX. Taking the normal from (a,b,c) alone gives the zero
        # vector there, and a zero normal is unlit: every hip and gable end
        # in every GLB this ever exported came out near-black. Try the other
        # corner before giving up.
        n = [0.0, 0.0, 0.0]
        m = 0.0
        for p, q, r in ((a, b, c), (a, c, d), (b, c, d)):
            u = [q[i] - p[i] for i in range(3)]
            v = [r[i] - p[i] for i in range(3)]
            k = [u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0]]
            m = math.sqrt(sum(t * t for t in k))
            if m > 1e-9:
                n = k
                break
        n = [k / (m or 1.0) for k in n]
        base = len(pos) // 3
        for p in (a, b, c, d):
            pos.extend(p)
            nrm.extend(n)
        idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])

    storeys = model.get("storeys", 1)
    per = model.get("storey_height_m", DEFAULT_CEILING_HEIGHT_M)
    x0, x1 = model["extent_m"]["x"]
    y0, y1 = model["extent_m"]["y"]

    rooms = model.get("rooms") or []

    def _room_on_level(r, level):
        base = r.get("base_level") or 0
        n = r.get("storeys")
        top = storeys if n is None else base + int(n)
        return base <= level < top

    for level in range(storeys):
        z = level * per
        # THE FLOOR IS THE ROOMS, NOT THE BOUNDING BOX. Emitting one slab
        # across extent_m gave every L-shaped plan a floor plate hanging in
        # mid-air past the walls — over the garage, out beyond the return —
        # which reads as a modelling error the moment anyone orbits it.
        above = [r for r in rooms if _room_on_level(r, level + 1)]
        floors = [r for r in rooms if _room_on_level(r, level)]
        if floors:
            for r in floors:
                fx0, fy0 = r["x"], r["y"]
                fx1, fy1 = fx0 + r["width_m"], fy0 + r["depth_m"]
                emit("slab", [(fx0, fy0, z), (fx1, fy0, z),
                              (fx1, fy1, z), (fx0, fy1, z)])
        else:
            emit("slab", [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])
        for w in model["walls"]:
            if not _wall_on_level(w, level):
                continue
            (ax, ay), (bx, by) = w["start"], w["end"]
            L = math.hypot(bx - ax, by - ay)
            if L <= 0:
                continue
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy * w["thickness_m"] / 2.0, ux * w["thickness_m"] / 2.0
            h = w["height_m"]
            # Internal only where a room actually sits on the other side at
            # THIS level; above a single-storey neighbour it is brickwork.
            shared = w.get("shared_storeys")
            faces_out = w["external"] or (shared is not None
                                          and level >= shared)
            mat = "brick" if faces_out else "plaster"
            ops = sorted(_openings_at(w, level), key=lambda o: o["along"])

            # THE FLOOR ZONE IS BUILT, NOT AIR. A wall is CEILING height
            # (2.4m); the storey is floor to floor (2.7m). Stopping the
            # brickwork at the ceiling left a 300mm dark slot running right
            # round the building at first-floor level in every render — the
            # joist zone, drawn as a hole. Carry the face up to the slab
            # above wherever a storey actually continues over this wall.
            band = 0.0
            if above and per > h:
                mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
                for r in above:
                    if (r["x"] - 0.35 <= mx <= r["x"] + r["width_m"] + 0.35
                            and r["y"] - 0.35 <= my
                            <= r["y"] + r["depth_m"] + 0.35):
                        band = per - h
                        break

            out_sgn = w.get("outward", 1)
            for sgn, face_mat in ((out_sgn, mat), (-out_sgn, "plaster")):
                px, py = ax + nx * sgn, ay + ny * sgn

                def P(s, zz):
                    return (px + ux * s, py + uy * s, z + zz)

                if band > 0:
                    emit(face_mat, [P(0, h), P(L, h), P(L, h + band),
                                    P(0, h + band)])

                if not ops:
                    emit(face_mat, [P(0, 0), P(L, 0), P(L, h), P(0, h)])
                    continue
                cursor = 0.0
                for o in ops:
                    a0, a1 = o["along"], o["along"] + o["width"]
                    zb = o.get("sill", 0.0) if o["kind"] != "door" else 0.0
                    zt = zb + o["height"]
                    if a0 > cursor:
                        emit(face_mat, [P(cursor, 0), P(a0, 0),
                                        P(a0, h), P(cursor, h)])
                    if zb > 0:
                        emit(face_mat, [P(a0, 0), P(a1, 0), P(a1, zb),
                                        P(a0, zb)])
                    if zt < h:
                        emit(face_mat, [P(a0, zt), P(a1, zt), P(a1, h),
                                        P(a0, h)])
                    cursor = a1
                if cursor < L:
                    emit(face_mat, [P(cursor, 0), P(L, 0), P(L, h),
                                    P(cursor, h)])

            # the pane or leaf, on the wall centreline
            for o in ops:
                a0, a1 = o["along"], o["along"] + o["width"]
                zb = o.get("sill", 0.0) if o["kind"] != "door" else 0.0
                zt = zb + o["height"]
                p0 = (ax + ux * a0, ay + uy * a0)
                p1 = (ax + ux * a1, ay + uy * a1)
                emit("glass" if o["kind"] != "door" else "door",
                     [(p0[0], p0[1], z + zb), (p1[0], p1[1], z + zb),
                      (p1[0], p1[1], z + zt), (p0[0], p0[1], z + zt)])

            # wall head — on top of the floor-zone band where there is one
            hz = z + h + band
            emit(mat, [(ax + nx, ay + ny, hz), (bx + nx, by + ny, hz),
                       (bx - nx, by - ny, hz), (ax - nx, ay - ny, hz)])

    # THE TOP STOREY HAS A CEILING, NOT RAFTERS. Below the top, the floor
    # slab of the storey above doubles as the ceiling; on the top floor
    # there is no slab, so every bedroom looked straight up into the dark
    # underside of the roof. That is a plasterboard ceiling at the room's
    # own height in any house that is not a barn conversion.
    if storeys:
        top_level = storeys - 1
        for r in rooms:
            if not _room_on_level(r, top_level):
                continue
            cz = top_level * per + float(r.get("height_m") or per)
            emit("plaster",
                 [(r["x"], r["y"], cz),
                  (r["x"], r["y"] + r["depth_m"], cz),
                  (r["x"] + r["width_m"], r["y"] + r["depth_m"], cz),
                  (r["x"] + r["width_m"], r["y"], cz)])

    for cap in model.get("caps") or []:
        cx, cy, cz = cap["x"], cap["y"], cap["z_m"]
        emit("tile", [(cx[0], cy[0], cz), (cx[1], cy[0], cz),
                      (cx[1], cy[1], cz), (cx[0], cy[1], cz)])

    roof = model.get("roof")
    if roof:
        ez = roof.get("eaves_tip_z_m", roof["eaves_z_m"])
        rz = roof["ridge_z_m"]
        for band in roof.get("range_list") or []:
            bx = band["band_m"]["x"]
            by = band["band_m"]["y"]
            (rax, ray), (rbx, rby) = band["ridge"]
            if roof["along_x"]:
                emit("tile", [(bx[0], by[0], ez), (bx[1], by[0], ez),
                              (rbx, rby, rz), (rax, ray, rz)])
                emit("tile", [(bx[1], by[1], ez), (bx[0], by[1], ez),
                              (rax, ray, rz), (rbx, rby, rz)])
                emit("tile", [(bx[0], by[0], ez), (rax, ray, rz),
                              (rax, ray, rz), (bx[0], by[1], ez)])
                emit("tile", [(bx[1], by[1], ez), (rbx, rby, rz),
                              (rbx, rby, rz), (bx[1], by[0], ez)])
            else:
                emit("tile", [(bx[0], by[0], ez), (bx[0], by[1], ez),
                              (rbx, rby, rz), (rax, ray, rz)])
                emit("tile", [(bx[1], by[1], ez), (bx[1], by[0], ez),
                              (rax, ray, rz), (rbx, rby, rz)])
                emit("tile", [(bx[0], by[0], ez), (rax, ray, rz),
                              (rax, ray, rz), (bx[1], by[0], ez)])
                emit("tile", [(bx[1], by[1], ez), (rbx, rby, rz),
                              (rbx, rby, rz), (bx[0], by[1], ez)])
    return out


def write_glb(model, path):
    """The building as a binary glTF 2.0 file.

    One file an app can hand straight to a viewer, to QuickLook on an
    iPhone, or to any 3D tool. Stdlib only — see the note above GLB_MATERIALS
    for why this does not go through Blender.
    """
    import struct
    import base64  # noqa: F401  (kept for callers that inline the buffer)

    groups = _glb_mesh(model)
    if not groups:
        raise ModelError("nothing to export — the model has no geometry")

    buf = bytearray()
    accessors, views, prims = [], [], []

    def pad4():
        while len(buf) % 4:
            buf.append(0)

    for name, (pos, nrm, idx) in groups.items():
        if not idx:
            continue
        # indices
        pad4()
        off = len(buf)
        buf.extend(struct.pack(f"<{len(idx)}I", *idx))
        views.append({"buffer": 0, "byteOffset": off,
                      "byteLength": len(idx) * 4, "target": 34963})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5125,
                          "count": len(idx), "type": "SCALAR",
                          "min": [min(idx)], "max": [max(idx)]})
        i_acc = len(accessors) - 1

        def vec3(data):
            pad4()
            o = len(buf)
            buf.extend(struct.pack(f"<{len(data)}f", *data))
            views.append({"buffer": 0, "byteOffset": o,
                          "byteLength": len(data) * 4, "target": 34962})
            xs, ys, zs = data[0::3], data[1::3], data[2::3]
            accessors.append({
                "bufferView": len(views) - 1, "componentType": 5126,
                "count": len(data) // 3, "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)]})
            return len(accessors) - 1

        p_acc = vec3(pos)
        n_acc = vec3(nrm)
        prims.append({"attributes": {"POSITION": p_acc, "NORMAL": n_acc},
                      "indices": i_acc, "material": _GLB_INDEX[name]})

    pad4()
    materials = []
    for name, rgba, metal, rough in GLB_MATERIALS:
        m = {"name": name,
             "pbrMetallicRoughness": {"baseColorFactor": list(rgba),
                                      "metallicFactor": metal,
                                      "roughnessFactor": rough},
             "doubleSided": True}
        if rgba[3] < 1.0:
            m["alphaMode"] = "BLEND"
        materials.append(m)

    gltf = {
        "asset": {"version": "2.0", "generator": "building-scan model mode"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "building"}],
        "meshes": [{"name": "building", "primitives": prims}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buf)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(js) % 4:
        js += b" "

    with open(path, "wb") as f:
        total = 12 + 8 + len(js) + 8 + len(buf)
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack("<II", len(buf), 0x004E4942))
        f.write(bytes(buf))
    return path


def _levels_of(w, storeys):
    """How many storeys a wall dict is actually built on."""
    base = w.get("base_level") or 0
    n = w.get("storeys")
    if n is None:
        return max(0, storeys - base)
    return max(0, min(base + n, storeys) - base)


def retotal(model):
    """Recompute the opening-dependent totals from the wall dicts.

    Exists because facade openings can now be REPLACED after build() — and a
    model whose walls changed while its take-off didn't is precisely the
    kind of quiet lie the audit went looking for.
    """
    storeys = model.get("storeys", 1)
    walls = model["walls"]

    def count(kind):
        return sum((_levels_of(w, storeys) if o.get("level") is None else 1)
                   for w in walls for o in w.get("openings", [])
                   if o["kind"] == kind)

    gross = sum(w["length_m"] * w["height_m"] * _levels_of(w, storeys)
                for w in walls)
    cut = sum(o["width"] * o["height"]
              * (_levels_of(w, storeys) if o.get("level") is None else 1)
              for w in walls for o in w.get("openings", []))
    for w in walls:
        wg = w["length_m"] * w["height_m"]
        wc = sum(o["width"] * o["height"] for o in w.get("openings", []))
        w["net_area_m2"] = round(max(0.0, wg - wc), 2)
    t = model["totals"]
    t["doors"] = count("door")
    t["windows"] = count("window")
    t["wall_area_net_m2"] = round(max(0.0, gross - cut), 2)
    return t


def apply_facade_openings(model, openings, facade_y=0.0):
    """Replace the rule-placed front openings with ones read from a photo.

    The rule spread one window per wall and could never know better. A photo
    of the elevation does know better, so its openings win on the facade —
    and ONLY on the facade: side and rear walls keep the rule until someone
    photographs them too.

    Refuses quietly rather than wrongly: an opening that lands outside every
    front wall, or overlaps one already placed, is skipped and counted. And
    a house keeps its front door — if the reading has no door (hidden behind
    a porch or a hedge, commonly), the rule-placed door survives the purge.
    """
    eps = 1e-6
    storeys = model.get("storeys", 1)
    fronts = [w for w in model["walls"] if w["external"]
              and abs(w["start"][1] - facade_y) < eps
              and abs(w["end"][1] - facade_y) < eps]
    if not fronts:
        return {"applied": 0, "skipped": len(openings),
                "why": "no external wall on the facade line"}

    saved_door = None
    for w in fronts:
        for o in w.get("openings", []):
            if o["kind"] == "door" and saved_door is None:
                saved_door = (w, dict(o))
        w["openings"] = []

    has_door = any(o["kind"] == "door" for o in openings)
    todo = list(openings)
    if not has_door and saved_door is not None:
        todo.append(dict(saved_door[1]))

    applied, skipped = 0, 0
    placed_spans = {id(w): [] for w in fronts}
    for o in sorted(todo, key=lambda o: o["along"]):
        hit = None
        for w in fronts:
            # A FACADE IS TWO STOREYS OF DIFFERENT WALLS. The ground floor
            # and the floor above rarely divide at the same points — lounge,
            # hall, garage below; master, en-suite, bedroom above — so the
            # first wall that merely spans the right x is very often the
            # wrong floor. The opening then carried level=1 onto a wall that
            # only exists at level 0, and _openings_at dropped it: every
            # upstairs window read off the photo vanished without a word.
            if o.get("level") is not None and not _wall_on_level(w, o["level"]):
                continue
            ax, bx = w["start"][0], w["end"][0]
            lo, hi = min(ax, bx), max(ax, bx)
            if o["along"] >= lo - eps and o["along"] + o["width"] <= hi + eps:
                hit = (w, ax, bx, lo, hi)
                break
        if hit is None:
            skipped += 1
            continue
        w, ax, bx, lo, hi = hit
        # Opening 'along' is measured along the wall FROM ITS START — flip
        # when the wall runs right-to-left, or every opening mirrors.
        local = (o["along"] - ax) if ax <= bx \
            else (ax - o["along"] - o["width"])
        local = max(0.05, min(local, w["length_m"] - o["width"] - 0.05))
        span = (local, local + o["width"], o.get("level"))
        if any(s0 < span[1] and span[0] < s1
               and (lv is None or span[2] is None or lv == span[2])
               for s0, s1, lv in placed_spans[id(w)]):
            skipped += 1
            continue
        placed_spans[id(w)].append(span)
        w["openings"].append({"kind": o["kind"], "along": round(local, 3),
                              "width": o["width"], "height": o["height"],
                              "sill": o.get("sill", 0.0),
                              "level": o.get("level")})
        applied += 1

    retotal(model)
    return {"applied": applied, "skipped": skipped,
            "door_preserved": (not has_door and saved_door is not None)}
