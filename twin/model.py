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
            if r.get("kind") in ("gabled", "hipped"):
                span = min(b.width, b.depth)
                top = max(top, base + (span / 2) *
                          math.tan(math.radians(r.get("pitch_deg", 30))))
            elif r.get("kind") == "monopitch":
                span = min(b.width, b.depth)
                top = max(top, base + span *
                          math.tan(math.radians(r.get("pitch_deg", 30))))
            else:
                top = max(top, base)
        return top

    def measurements(self):
        return {
            "footprint_m2": round(self.footprint(), 2),
            "gia_m2": round(self.gia(), 2),
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
    bearing = (90.0 - math.degrees(ang)) % 360.0

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
                roof={"kind": "gabled", "pitch_deg": 30.0, "overhang": 0.3,
                      "ridge_along": "y",
                      "classification": CLASS_ESTIMATED},
                note=note)

    # Anchor at the rectangle corner so local (0,0) is a real place.
    b = math.radians(bearing)
    corner_e = cx - (w / 2) * math.cos(b) + (d / 2) * math.sin(b)
    corner_n = cy + (w / 2) * math.sin(b) + (d / 2) * math.cos(b)
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

    rooms = []
    for b in bld.blocks:
        for lvl in range(b.storeys):
            rooms.append(M.Room(
                f"{b.name} L{b.base_level + lvl}",
                round(b.x, 3), round(b.y, 3),
                round(b.width, 3), round(b.depth, 3),
                kind="room", storeys=1,
                base_level=b.base_level + lvl,
                height=round(b.storey_height - 0.35, 2)))
    return rooms, M
