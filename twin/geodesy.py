"""Measuring on a round earth, correctly, without pyproj.

Every number the user reads off this platform — a footprint area, a wall
length, an extension depth — is computed here. Getting it wrong is not a
rendering bug, it is a wrong quantity on a real order, so the choices
are deliberate:

AREAS USE THE GEODESIC FORMULA, not the shoelace on lon/lat. Treating
degrees as a plane over-measures east-west by 1/cos(latitude) — 38% at
Birmingham's 52.5°N, which on a 100 m2 footprint is 38 m2 of invented
house. The spherical excess formula below is exact on a sphere and
within ~0.3% of the ellipsoidal answer at any UK-sized polygon.

DISTANCES USE HAVERSINE on the mean earth radius. Millimetre-accurate
geodesics (Vincenty/Karney) matter over hundreds of kilometres; over a
building they agree to well under the 3 m the footprint itself is
accurate to, and haversine cannot fail to converge.

LOCAL METRES USE A TANGENT PLANE at a stated origin. The editor works in
metres — snapping, dragging, orthogonality all need a flat frame — and
over a plot the tangent plane is exact to well under a millimetre.
"""
from __future__ import annotations

import math

R_EARTH = 6371008.8          # IUGG mean radius, metres — see local_radius
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def local_radius(lat_deg: float) -> float:
    """Gaussian radius of curvature at a latitude.

    THE MEAN RADIUS IS THE WRONG RADIUS. Spherical-excess area on the
    6371 km mean sphere under-measures at UK latitudes by 0.4%, because
    the real earth is fatter than the mean there: at 52.5N the local
    radius is 6383.6 km, and area goes as the square of it. Caught by
    building a square from ellipsoidal metre offsets and measuring it
    back — it came out 398.4 m2 instead of 400. Small, systematic, and
    in a number people order materials against, which is the definition
    of the kind of error worth fixing rather than documenting.

    sqrt(M*N) — meridional times prime-vertical — is the standard local
    sphere approximation and lands inside 0.01% for a polygon this size.
    """
    s = math.sin(math.radians(lat_deg))
    w = math.sqrt(1.0 - WGS84_E2 * s * s)
    m = WGS84_A * (1.0 - WGS84_E2) / (w ** 3)      # meridional
    n = WGS84_A / w                                # prime vertical
    return math.sqrt(m * n)


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres, on the LOCAL sphere."""
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2)
    r = local_radius((lat1 + lat2) / 2.0)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def geodesic_area(ring) -> float:
    """Area in m2 of a [[lon,lat],...] ring, by spherical excess.

    Sign-independent: returns the magnitude, because a GeoJSON ring's
    winding tells you inside from outside, not how big it is.
    """
    if len(ring) < 4:
        return 0.0
    pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
    n = len(pts)
    if n < 3:
        return 0.0
    p = math.pi / 180.0
    total = 0.0
    for i in range(n):
        lon1, lat1 = pts[i]
        lon2, lat2 = pts[(i + 1) % n]
        total += (lon2 - lon1) * p * (2 + math.sin(lat1 * p)
                                      + math.sin(lat2 * p))
    r = local_radius(sum(pt[1] for pt in pts) / n)
    return abs(total * r * r / 2.0)


def polygon_area(geometry) -> float:
    """m2 of a GeoJSON Polygon or MultiPolygon, holes subtracted."""
    if not geometry:
        return 0.0
    t = geometry.get("type")
    if t == "Polygon":
        rings = [geometry["coordinates"]]
    elif t == "MultiPolygon":
        rings = geometry["coordinates"]
    else:
        return 0.0
    total = 0.0
    for poly in rings:
        if not poly:
            continue
        total += geodesic_area(poly[0])
        for hole in poly[1:]:
            total -= geodesic_area(hole)
    return max(0.0, total)


def perimeter(geometry) -> float:
    """Metres around the outer ring(s)."""
    if not geometry:
        return 0.0
    t = geometry.get("type")
    polys = ([geometry["coordinates"]] if t == "Polygon"
             else geometry["coordinates"] if t == "MultiPolygon" else [])
    total = 0.0
    for poly in polys:
        if not poly:
            continue
        ring = poly[0]
        for i in range(len(ring) - 1):
            total += haversine(ring[i][1], ring[i][0],
                               ring[i + 1][1], ring[i + 1][0])
    return total


def centroid(geometry):
    """Area-weighted centroid (lon, lat) of a polygon.

    The vertex mean is wrong for any shape with unevenly spaced points —
    an L-plan traced with ten nodes down one side pulls the "centre"
    into that side — and this centroid anchors the local frame, so the
    error would propagate into every edited coordinate.
    """
    t = (geometry or {}).get("type")
    polys = ([geometry["coordinates"]] if t == "Polygon"
             else geometry["coordinates"] if t == "MultiPolygon" else [])
    ax = ay = aa = 0.0
    for poly in polys:
        if not poly:
            continue
        ring = poly[0]
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        if len(pts) < 3:
            continue
        # Planar centroid in a locally scaled frame, then weighted by the
        # geodesic area so multipart shapes combine correctly.
        lat0 = sum(p[1] for p in pts) / len(pts)
        k = math.cos(math.radians(lat0))
        cx = cy = a2 = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i][0] * k, pts[i][1]
            x2, y2 = pts[(i + 1) % len(pts)][0] * k, pts[(i + 1) % len(pts)][1]
            cr = x1 * y2 - x2 * y1
            a2 += cr
            cx += (x1 + x2) * cr
            cy += (y1 + y2) * cr
        if abs(a2) < 1e-15:
            continue
        w = geodesic_area(ring)
        ax += (cx / (3 * a2) / k) * w
        ay += (cy / (3 * a2)) * w
        aa += w
    if aa <= 0:
        return None
    return [ax / aa, ay / aa]


def point_in_polygon(lon, lat, geometry) -> bool:
    """Ray casting, holes honoured. Used for property selection."""
    t = (geometry or {}).get("type")
    polys = ([geometry["coordinates"]] if t == "Polygon"
             else geometry["coordinates"] if t == "MultiPolygon" else [])

    def _in(ring):
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > lat) != (y2 > lat):
                xin = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-15)
                if lon < xin:
                    inside = not inside
        return inside

    for poly in polys:
        if not poly:
            continue
        if _in(poly[0]) and not any(_in(h) for h in poly[1:]):
            return True
    return False


class LocalFrame:
    """A tangent plane in metres about an origin — the editor's frame.

    +x is east, +y is north. Exact to sub-millimetre over a plot, which
    is the only scale it is ever used at; a caller that tries to convert
    a point kilometres away gets a warning rather than silent drift.
    """

    MAX_RANGE_M = 5000.0

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = float(lat0), float(lon0)
        # Metres per degree at this latitude, on the WGS84 ellipsoid.
        p = math.radians(self.lat0)
        self.m_lat = (111132.92 - 559.82 * math.cos(2 * p)
                      + 1.175 * math.cos(4 * p) - 0.0023 * math.cos(6 * p))
        self.m_lon = (111412.84 * math.cos(p) - 93.5 * math.cos(3 * p)
                      + 0.118 * math.cos(5 * p))

    def to_m(self, lon, lat):
        return ((lon - self.lon0) * self.m_lon,
                (lat - self.lat0) * self.m_lat)

    def to_lonlat(self, x, y):
        return (self.lon0 + x / self.m_lon, self.lat0 + y / self.m_lat)

    def ring_to_m(self, ring):
        return [list(self.to_m(p[0], p[1])) for p in ring]

    def ring_to_lonlat(self, ring):
        return [list(self.to_lonlat(p[0], p[1])) for p in ring]


def bbox_of(geometry):
    """[west, south, east, north] of any GeoJSON geometry."""
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (int, float)):
            return
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1]); return
        for sub in c:
            walk(sub)

    walk((geometry or {}).get("coordinates") or [])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def bearing(lat1, lon1, lat2, lon2) -> float:
    """Initial compass bearing, degrees from north."""
    p = math.pi / 180.0
    y = math.sin((lon2 - lon1) * p) * math.cos(lat2 * p)
    x = (math.cos(lat1 * p) * math.sin(lat2 * p)
         - math.sin(lat1 * p) * math.cos(lat2 * p) * math.cos((lon2 - lon1) * p))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
