"""THE authoritative building model. One geometry, every view.

The brief is explicit and it is the right call: "Maintain one
authoritative geometry model behind both interfaces. Do not maintain
disconnected fake 2D and 3D representations." So this module is the
single source of truth, and the 3D viewer, the floor plan, the
quantities and the regulations check are all READERS of it. Editing
happens through commands.py, never by touching two pictures.

THE FRAME. Everything is metres on a tangent plane whose origin is a
corner of the building and whose +y axis runs along the building's
depth, +x along its frontage. Working in a building-aligned frame rather
than north-up is what makes a rear extension "extend +y" instead of
"extend along a bearing of 20.4 degrees", and it is what lets the
existing building/model3d.py engine — which wants axis-aligned rectangles
— consume this without a reprojection step that could silently rotate a
house.

WHAT IS MEASURED AND WHAT IS NOT, per element. A footprint traced by OSM
volunteers is `verified` as published. A storey count inferred from a
LIDAR height is `derived`. A wall the user drags is `user`. The model
carries that per element and never averages it away — a drawing that
cannot tell you which of its lines were surveyed is a drawing nobody
should build from.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from . import geodesy
from .provenance import (CLASS_DERIVED, CLASS_ESTIMATED, CLASS_USER,
                         CLASS_VERIFIED, Provenance)

DEFAULT_STOREY_H = 2.65
DEFAULT_WALL_T = 0.3
MIN_WALL_M = 0.3


# --------------------------------------------------------------- shapes
def oriented_bbox(ring):
    """Minimum-area rectangle around a ring: (cx, cy, w, d, bearing_rad).

    Rotating calipers over the convex hull. The axis-aligned bbox is the
    wrong tool here — a house at 20 degrees to north gets a bbox 25%
    too big, and every quantity derived from it inherits that.
    """
    pts = [tuple(p) for p in (ring[:-1] if ring[0] == ring[-1] else ring)]
    if len(pts) < 3:
        raise ValueError("need at least 3 points")
    hull = _convex_hull(pts)
    best = None
    for i in range(len(hull)):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % len(hull)]
        ang = math.atan2(by - ay, bx - ax)
        c, s = math.cos(-ang), math.sin(-ang)
        xs = [p[0] * c - p[1] * s for p in hull]
        ys = [p[0] * s + p[1] * c for p in hull]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if best is None or w * h < best[0]:
            cx = (max(xs) + min(xs)) / 2
            cy = (max(ys) + min(ys)) / 2
            # back to world
            best = (w * h, cx * c + cy * s, -cx * s + cy * c, w, h, ang)
    _, cx, cy, w, h, ang = best
    return cx, cy, w, h, ang


def _convex_hull(pts):
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts

    def half(points):
        out = []
        for p in points:
            while len(out) >= 2:
                (ox, oy), (px, py) = out[-2], out[-1]
                if (px - ox) * (p[1] - oy) - (py - oy) * (p[0] - ox) > 0:
                    break
                out.pop()
            out.append(p)
        return out

    return half(pts)[:-1] + half(reversed(pts))[:-1]


def polygon_area_m(ring):
    """Shoelace, in a metric frame. Metres in, m2 out."""
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def rect_ring(x, y, w, d):
    return [[x, y], [x + w, y], [x + w, y + d], [x, y + d], [x, y]]


# --------------------------------------------------------------- pieces
@dataclass
class Block:
    """A rectangular mass: the house, or an extension, or a garage.

    Rectangles rather than free polygons because every downstream
    consumer — the regulations check, the quantities take-off, the floor
    plan — is built on them, and because a rear extension IS a rectangle.
    A free-form footprint is carried on the Building as the traced
    outline and reconciled against the blocks, with the difference
    reported rather than hidden.
    """
    id: str
    name: str
    x: float
    y: float
    width: float
    depth: float
    storeys: int = 2
    base_level: int = 0
    storey_height: float = DEFAULT_STOREY_H
    classification: str = CLASS_USER
    roof: Optional[dict] = None
    note: str = ""

    def ring(self):
        return rect_ring(self.x, self.y, self.width, self.depth)

    def area(self):
        return self.width * self.depth

    def gia(self):
        return self.area() * self.storeys

    def edges(self):
        """(id, name, [p0, p1], outward_normal) for each side."""
        x0, y0, x1, y1 = self.x, self.y, self.x + self.width, self.y + self.depth
        return [
            (f"{self.id}:front", "front", [[x0, y0], [x1, y0]], (0.0, -1.0)),
            (f"{self.id}:right", "right", [[x1, y0], [x1, y1]], (1.0, 0.0)),
            (f"{self.id}:rear", "rear", [[x1, y1], [x0, y1]], (0.0, 1.0)),
            (f"{self.id}:left", "left", [[x0, y1], [x0, y0]], (-1.0, 0.0)),
        ]

    def as_dict(self):
        d = asdict(self)
        d.update(ring=self.ring(), area_m2=round(self.area(), 2),
                 gia_m2=round(self.gia(), 2))
        return d


@dataclass
class Room:
    """A room inside a block, on one level. The unit the REGULATIONS see.

    Until rooms exist the regulations gate can only say "massing": there
    is no hall for a stair to rise from, no habitable room to need an
    escape window, no wet room to extract from. A room is therefore not
    decoration on the drawing — it is what turns a compliance verdict
    from a shrug into an answer.

    `kind` is the load-bearing field. buildable.py branches on
    circulation / room / kitchen / wet, and getting it wrong is how a
    hall becomes a bedroom that needs a window.
    """
    id: str
    block_id: str
    level: int
    name: str
    kind: str                # room | circulation | kitchen | wet | store
    x: float
    y: float
    width: float
    depth: float
    classification: str = CLASS_USER

    def ring(self):
        return rect_ring(self.x, self.y, self.width, self.depth)

    def area(self):
        return self.width * self.depth

    def as_dict(self):
        d = asdict(self)
        d.update(ring=self.ring(), area_m2=round(self.area(), 2))
        return d


ROOM_KINDS = ("room", "circulation", "kitchen", "wet", "store")

# Minimum sensible dimensions. Not regulations — Part K and the NDSS have
# the real numbers and buildable.py checks them — but a partition dragged
# to 400 mm is a mistake, not a design, and refusing it early is kinder
# than a compliance failure three screens later.
MIN_ROOM_M = 0.9
MIN_ROOM_AREA_M2 = 1.2


@dataclass
class Opening:
    id: str
    block_id: str
    edge: str                 # "front" | "rear" | "left" | "right"
    kind: str                 # "window" | "door" | "bifold" | "rooflight"
    along_m: float            # from the edge's start
    width: float
    height: float
    sill: float = 0.9
    level: int = 0
    classification: str = CLASS_USER

    def as_dict(self):
        return asdict(self)


@dataclass
class Building:
    """The whole twin: what is there, what is proposed, and who says so."""
    id: str
    anchor_lat: float
    anchor_lon: float
    bearing_deg: float                 # compass bearing of local +y
    blocks: List[Block] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    openings: List[Opening] = field(default_factory=list)
    traced_ring: Optional[list] = None       # the real outline, in metres
    source: Optional[dict] = None            # provenance of the footprint
    address: Optional[str] = None
    ground_m_aod: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    # -- frames ------------------------------------------------------
    def frame(self):
        return geodesy.LocalFrame(self.anchor_lat, self.anchor_lon)

    def to_lonlat(self, x, y):
        """Building-frame metres -> (lon, lat). Rotation then tangent."""
        b = math.radians(self.bearing_deg)
        east = x * math.cos(b) + y * math.sin(b)
        north = -x * math.sin(b) + y * math.cos(b)
        f = self.frame()
        return f.to_lonlat(east, north)

    def from_lonlat(self, lon, lat):
        f = self.frame()
        east, north = f.to_m(lon, lat)
        b = math.radians(self.bearing_deg)
        return (east * math.cos(b) - north * math.sin(b),
                east * math.sin(b) + north * math.cos(b))

    def ring_to_lonlat(self, ring):
        return [list(self.to_lonlat(p[0], p[1])) for p in ring]

    # -- reads -------------------------------------------------------
    def block(self, block_id):
        for b in self.blocks:
            if b.id == block_id:
                return b
        return None

    def room(self, room_id):
        for r in self.rooms:
            if r.id == room_id:
                return r
        return None

    def rooms_on(self, level):
        return [r for r in self.rooms if r.level == level]

    def has_rooms(self):
        return bool(self.rooms)

    def existing(self):
        """The block that came from the survey, not from an edit."""
        for b in self.blocks:
            if b.classification in (CLASS_VERIFIED, CLASS_DERIVED):
                return b
        return self.blocks[0] if self.blocks else None

    def gia(self):
        return sum(b.gia() for b in self.blocks)

    def footprint(self):
        return sum(b.area() for b in self.blocks)

    def eaves_m(self):
        return max((b.base_level + b.storeys) * b.storey_height
                   for b in self.blocks) if self.blocks else 0.0

    def ridge_m(self):
        top = 0.0
        for b in self.blocks:
            base = (b.base_level + b.storeys) * b.storey_height
            r = b.roof or {}
            t = math.tan(math.radians(r.get("pitch_deg", 30)))
            # The slope runs ACROSS the ridge the spec names, exactly as
            # the 3D draws it; min(w, d) was a third convention that
            # understated the schedule's ridge height whenever the roof
            # climbed the longer side.
            ra = r.get("ridge_along")
            if ra not in ("x", "y"):
                ra = "y" if b.depth >= b.width else "x"
            span = b.depth if ra == "x" else b.width
            if r.get("kind") == "gabled":
                top = max(top, base + (span / 2) * t)
            elif r.get("kind") == "hipped":
                top = max(top, base + (min(b.width, b.depth) / 2) * t)
            elif r.get("kind") == "monopitch":
                top = max(top, base + span * t)
            else:
                top = max(top, base)
        return top

    def measurements(self):
        return {
            "footprint_m2": round(self.footprint(), 2),
            "gia_m2": round(self.gia(), 2),
            "rooms": len(self.rooms),
            "room_area_m2": round(sum(r.area() for r in self.rooms), 2),
            "eaves_height_m": round(self.eaves_m(), 2),
            "ridge_height_m": round(self.ridge_m(), 2),
            "blocks": [{"id": b.id, "name": b.name,
                        "area_m2": round(b.area(), 2),
                        "gia_m2": round(b.gia(), 2),
                        "storeys": b.storeys,
                        "classification": b.classification}
                       for b in self.blocks],
        }

    def geojson(self):
        """Every block as a georeferenced feature, classification intact."""
        feats = []
        for b in self.blocks:
            feats.append({
                "type": "Feature", "id": b.id,
                "geometry": {"type": "Polygon",
                             "coordinates": [self.ring_to_lonlat(b.ring())]},
                "properties": {"name": b.name, "storeys": b.storeys,
                               "classification": b.classification,
                               "area_m2": round(b.area(), 2),
                               "note": b.note},
            })
        if self.traced_ring:
            feats.append({
                "type": "Feature", "id": "traced",
                "geometry": {"type": "Polygon",
                             "coordinates": [
                                 self.ring_to_lonlat(self.traced_ring)]},
                "properties": {"name": "surveyed outline",
                               "classification": CLASS_VERIFIED},
            })
        return {"type": "FeatureCollection", "features": feats}

    def as_dict(self):
        return {
            "id": self.id,
            "anchor": {"lat": self.anchor_lat, "lon": self.anchor_lon,
                       "bearing_deg": self.bearing_deg},
            "address": self.address,
            "ground_m_aod": self.ground_m_aod,
            "blocks": [b.as_dict() for b in self.blocks],
            "rooms": [r.as_dict() for r in self.rooms],
            "openings": [o.as_dict() for o in self.openings],
            "traced_ring": self.traced_ring,
            "source": self.source,
            "measurements": self.measurements(),
            "geojson": self.geojson(),
            "notes": self.notes,
        }


# ------------------------------------------------------- construction
def from_footprint(feature, *, lidar=None, address=None, storey_height=None):
    """Build a twin from a REAL selected footprint. Nothing invented.

    Storeys come from an OSM tag if there is one (verified), otherwise
    from the LIDAR height divided by a storey (derived, and said so),
    otherwise the model carries NO storey count and the caller must ask.
    The one thing this must never do is default quietly to two.
    """
    geom = feature["geometry"]
    ring_ll = (geom["coordinates"][0] if geom["type"] == "Polygon"
               else geom["coordinates"][0][0])
    centre = geodesy.centroid(geom)
    f = geodesy.LocalFrame(centre[1], centre[0])
    ring_m = [list(f.to_m(p[0], p[1])) for p in ring_ll]

    cx, cy, w, d, ang = oriented_bbox(ring_m)
    # The long axis is the depth of a UK terrace/semi far more often than
    # not, and the FRONT is the short side. Orient so +y runs along the
    # longer dimension; the bearing records the truth either way.
    if w > d:
        w, d = d, w
        ang += math.pi / 2
    # BEARING IS THE COMPASS BEARING OF LOCAL +Y, WHICH IS DEPTH.
    # `ang` is the angle of the WIDTH axis, so taking 90 - ang gave the
    # bearing of the wrong side and rotated every model 90 degrees off
    # the real building. Depth runs along (-sin ang, cos ang) in
    # east/north, whose compass bearing is -ang.
    bearing = (-math.degrees(ang)) % 360.0

    props = feature.get("properties", {}) or {}
    storeys, storeys_class, note = None, None, ""
    lv = props.get("levels")
    if lv not in (None, ""):
        try:
            storeys = max(1, int(float(str(lv).split()[0])))
            storeys_class = CLASS_VERIFIED
            note = "storeys from the OpenStreetMap building:levels tag"
        except ValueError:
            pass
    sh = storey_height or DEFAULT_STOREY_H
    if storeys is None and lidar and lidar.get("height_above_ground_m"):
        h = float(lidar["height_above_ground_m"])
        if h > 1.5:
            storeys = max(1, int(round(h / sh)))
            storeys_class = CLASS_DERIVED
            note = (f"storeys derived from a LIDAR height of {h:.1f} m "
                    f"at {sh:.2f} m per storey — the roof is included in "
                    f"that height, so this is a reading, not a survey")
    if storeys is None:
        storeys = 1
        storeys_class = CLASS_ESTIMATED
        note = ("NO storey count is published for this building and no "
                "LIDAR height was available: one storey is assumed and "
                "must be corrected before anything is ordered")

    # Local frame: origin at the rectangle's near-left corner, +y depth.
    blk = Block(id="existing", name="Existing building",
                x=0.0, y=0.0, width=round(w, 3), depth=round(d, 3),
                storeys=storeys, storey_height=sh,
                classification=storeys_class or CLASS_ESTIMATED,
                # The estimated ridge follows the LONGER plan side, the
                # way a UK roof almost always does — hardcoding "y" put
                # the ridge across the frontage of any house wider than
                # it is deep.
                roof={"kind": "gabled", "pitch_deg": 30.0, "overhang": 0.3,
                      "ridge_along": "y" if d >= w else "x",
                      "classification": CLASS_ESTIMATED},
                note=note)

    # Anchor at the rectangle corner so local (0,0) is a real place.
    #
    # The block sits at x in [0, w], y in [0, d], so its centre is at
    # (w/2, d/2) in the building frame and the anchor is the rectangle
    # centre MINUS that offset rotated into east/north. to_lonlat uses
    # [[cos b, sin b], [-sin b, cos b]], so both depth terms subtract;
    # adding them put the origin on the opposite corner and slid the
    # whole model off the building it was fitted to.
    b = math.radians(bearing)
    corner_e = cx - (w / 2) * math.cos(b) - (d / 2) * math.sin(b)
    corner_n = cy + (w / 2) * math.sin(b) - (d / 2) * math.cos(b)
    alon, alat = f.to_lonlat(corner_e, corner_n)

    bld = Building(id=uuid.uuid4().hex[:12], anchor_lat=alat, anchor_lon=alon,
                   bearing_deg=bearing, blocks=[blk], address=address,
                   source=props.get("provenance"),
                   ground_m_aod=(lidar or {}).get("ground_m_aod"))
    bld.traced_ring = [list(bld.from_lonlat(p[0], p[1])) for p in ring_ll]

    traced = polygon_area_m(bld.traced_ring)
    rect = blk.area()
    if rect > 0 and abs(traced - rect) / rect > 0.06:
        bld.notes.append(
            f"The surveyed outline measures {traced:.1f} m2 but the "
            f"rectangle fitted to it is {rect:.1f} m2 "
            f"({abs(traced - rect) / rect * 100:.0f}% apart). This "
            f"building is not rectangular: quantities from the rectangle "
            f"are indicative until the shape is edited to match.")
    if storeys_class == CLASS_ESTIMATED:
        bld.notes.append(note)
    return bld


# ------------------------------------------------- room geometry
def rect_union_area(rects):
    """Union area of axis-aligned rectangles, exactly.

    The obvious sum double-counts wherever two rectangles overlap, and
    the coverage test built on the sum was provably wrong: two stacked
    rooms in one corner summed to 75% of a block that was 62% bare, so
    the whole-block fallback was suppressed and most of the floor plate
    vanished from the engine. Coordinate compression is a dozen lines
    and exact, so there is no reason to approximate.
    """
    rects = [(x0, y0, x1, y1) for x0, y0, x1, y1 in rects
             if x1 - x0 > 1e-12 and y1 - y0 > 1e-12]
    if not rects:
        return 0.0
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    ys = sorted({v for r in rects for v in (r[1], r[3])})
    area = 0.0
    for i in range(len(xs) - 1):
        cx = (xs[i] + xs[i + 1]) / 2.0
        for j in range(len(ys) - 1):
            cy = (ys[j] + ys[j + 1]) / 2.0
            if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3]
                   for r in rects):
                area += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
    return area


def room_block_overlap(room, blk):
    """Plan-area overlap between a room and a block, in m²."""
    ox = min(blk.x + blk.width, room.x + room.width) - max(blk.x, room.x)
    oy = min(blk.y + blk.depth, room.y + room.depth) - max(blk.y, room.y)
    return max(0.0, ox) * max(0.0, oy)


def room_inside_building(bld, room, tol=1e-6):
    """Is the room's whole rectangle inside SOME block on its level?

    This is the containment test everything must use instead of "inside
    the block named by room.block_id": the moment a knock-through makes
    one room across two blocks, the anchor block stops being the
    container, and every check still using it either refuses a genuinely
    internal wall or lets a room hang in the open air.
    """
    inside = rect_union_area([
        (max(b.x, room.x), max(b.y, room.y),
         min(b.x + b.width, room.x + room.width),
         min(b.y + b.depth, room.y + room.depth))
        for b in bld.blocks
        if b.base_level <= room.level < b.base_level + b.storeys])
    return inside >= room.area() - tol


# --------------------------------------------- bridge to building/
def to_engine_rooms(bld):
    """Blocks -> building/model3d Room list, for the real pipeline.

    This is the join that makes the twin more than a viewer: the same
    regulations gate, take-off and IFC export the rest of this project
    already does, driven by what the user just dragged on screen.
    """
    import sys
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), "building")
    if p not in sys.path:
        sys.path.insert(0, p)
    import model3d as M

    # REAL ROOMS WHEN THEY EXIST. A block with rooms drawn in it goes to
    # the engine as those rooms, so the regulations gate sees a hall, a
    # kitchen and a bathroom rather than one solid lump. Only a block
    # with nothing drawn in it falls back to being its own room, and
    # design.assess labels that case "massing" so nobody mistakes the
    # resulting refusals for a verdict on the design.
    # A ROOM CAN SPAN TWO BLOCKS. Knocking a kitchen through into a rear
    # extension makes one room across the old wall, which is the whole
    # point of the job — so the fallback cannot be "this block has no
    # rooms OF ITS OWN". It must be "this block is not covered by any
    # room", or the extension gets a phantom room laid over the real one
    # and the gate reports an island that cannot be entered.
    rooms = []
    for r in bld.rooms:
        # Ceiling height from the room's OWN block where it still means
        # something, else any block on the level — a room spanning two
        # blocks of different heights is inherently ambiguous, but a
        # room inside its own block must use that block's.
        h = None
        own = bld.block(r.block_id)
        candidates = ([own] if own is not None else []) + bld.blocks
        for b in candidates:
            if b.base_level <= r.level < b.base_level + b.storeys:
                h = round(b.storey_height - 0.35, 2)
                break
        rooms.append(M.Room(
            r.name, round(r.x, 3), round(r.y, 3),
            round(r.width, 3), round(r.depth, 3),
            kind=r.kind, storeys=1, base_level=r.level,
            height=h or (DEFAULT_STOREY_H - 0.35)))

    def _covered(blk, level):
        """Fraction of a block's plan occupied by the UNION of rooms."""
        area = blk.width * blk.depth
        if area <= 0:
            return 1.0
        hit = rect_union_area([
            (max(blk.x, r.x), max(blk.y, r.y),
             min(blk.x + blk.width, r.x + r.width),
             min(blk.y + blk.depth, r.y + r.depth))
            for r in bld.rooms if r.level == level])
        return hit / area

    for b in bld.blocks:
        for lvl in range(b.storeys):
            level = b.base_level + lvl
            if _covered(b, level) > 0.6:
                continue
            rooms.append(M.Room(
                f"{b.name} L{level}",
                round(b.x, 3), round(b.y, 3),
                round(b.width, 3), round(b.depth, 3),
                kind="room", storeys=1, base_level=level,
                height=round(b.storey_height - 0.35, 2)))
    return rooms, M


def auto_layout(bld, block_id, level=0, id_seed=None, id_start=0):
    """A sensible STARTING layout for a block, not a design.

    A blank rectangle is a bad place to start from and a wrong place to
    stay: the gate needs a hall, and a user asked to draw one from
    nothing will not bother. This lays out the ordinary UK arrangement
    for the level — hall down one side on the ground floor with the
    living space beside it and the kitchen at the back; landing and
    bedrooms above — sized to whatever the block actually is.

    It is explicitly a starting point. Every room is user-classified and
    every partition is draggable, and the note says so.

    `id_seed` MATTERS MORE THAN IT LOOKS. Undo replays the history, so a
    room id minted from a fresh uuid on every apply() comes back
    different after an undo/redo round trip — the same room under a new
    name, which strands the selection and refuses the next command that
    names it. The caller mints one seed when the command is constructed
    and the ids fall out of it deterministically.
    """
    blk = bld.block(block_id)
    if blk is None:
        raise ValueError(f"no block {block_id!r}")
    if not (blk.base_level <= level < blk.base_level + blk.storeys):
        raise ValueError(f"block {block_id!r} has no level {level}")
    w, d = blk.width, blk.depth
    out = []
    # AN EXTENSION IS NOT A HOUSE. Laying a hall-and-rooms plan into a
    # 4 m rear extension produces rooms reached through rooms, which the
    # gate correctly refuses as inner rooms. What actually gets built is
    # one open space, so that is what is laid out — and it is the user's
    # to change.
    #
    # DETECTED BY SIZE, NOT BY CLASSIFICATION. The first version asked
    # "is some other block survey-classified" — but MoveWall marks the
    # house as user-edited the moment its wall is corrected, after which
    # a 4 m extension got the full hall-and-rooms treatment and the gate
    # refused the layout's own inner rooms. A block half the size of a
    # neighbour it stands against is the annexe whatever the labels say.
    is_extension = any(o is not blk and o.area() >= 2.0 * blk.area()
                       for o in bld.blocks)

    seed = id_seed or uuid.uuid4().hex[:6]

    def R(name, kind, x, y, rw, rd):
        out.append(Room(
            id=f"rm-{seed}-{id_start + len(out)}",
            block_id=blk.id, level=level,
            name=name, kind=kind, x=round(blk.x + x, 3),
            y=round(blk.y + y, 3), width=round(rw, 3), depth=round(rd, 3)))

    def one_room():
        out.clear()
        R("Kitchen/diner" if is_extension else "Room",
          "kitchen" if is_extension else "room", 0, 0, w, d)
        return out

    # A hall wide enough to be one, but never more than a third of the
    # frontage — on a narrow terrace that is what actually gets built.
    # The subdivision needs room for every band it makes: a kitchen of
    # at least ~2 m and a front zone of 2.5 m, so anything shallower
    # than 4.5 m stays one space rather than being minced.
    hall_w = max(0.9, min(1.95, w * 0.33))
    if is_extension or w < 2.4 or d < 4.5:
        return one_room()

    # BAND EDGES ARE ROUNDED COORDINATES, DEPTHS ARE THEIR DIFFERENCES.
    # Rounding each band's depth separately meant Dining's rear edge
    # (round(a)+round(b)) and Kitchen's front edge (round(a+b)) could
    # disagree by a millimetre — outside the partition-pairing tolerance,
    # so a dragged wall sailed through its neighbour. Rounding the CUT
    # LINES once and deriving depths from consecutive cuts makes the
    # bands tile exactly, always.
    if level == blk.base_level:
        kitchen_d = max(2.0, min(max(3.0, d * 0.34), d - 2.5))
        front_d = d - kitchen_d
        y_split = round(front_d * 0.58, 3)
        y_kitchen = round(front_d, 3)
        R("Hall", "circulation", 0, 0, hall_w, y_kitchen)
        R("Living room", "room", hall_w, 0, w - hall_w, y_split)
        R("Dining room", "room", hall_w, y_split,
          w - hall_w, y_kitchen - y_split)
        R("Kitchen", "kitchen", 0, y_kitchen, w, d - y_kitchen)
    else:
        bath_d = max(1.5, min(max(1.9, d * 0.2), d - 3.0))
        rest_d = d - bath_d
        y_split = round(rest_d * 0.55, 3)
        y_bath = round(rest_d, 3)
        R("Landing", "circulation", 0, 0, hall_w, y_bath)
        R("Bedroom 1", "room", hall_w, 0, w - hall_w, y_split)
        R("Bedroom 2", "room", hall_w, y_split,
          w - hall_w, y_bath - y_split)
        R("Bathroom", "wet", 0, y_bath, w, d - y_bath)

    # THE LAYOUT MUST OBEY ITS OWN RULES. AddRoom and MovePartition
    # refuse anything under MIN_ROOM_M; a starting layout that mints a
    # 0.7 m kitchen or a zero-depth bathroom hands the user a plan the
    # editor itself would have refused. If the arithmetic cannot fit
    # legal rooms into this block, one open room is the honest layout.
    for r in out:
        if (r.width < MIN_ROOM_M - 1e-9 or r.depth < MIN_ROOM_M - 1e-9
                or r.area() < MIN_ROOM_AREA_M2 - 1e-9):
            return one_room()
    return out
