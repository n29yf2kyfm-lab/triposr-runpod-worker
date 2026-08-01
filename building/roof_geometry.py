"""Roof geometry from an elevation point set — pure stdlib.

Takes points on a roof surface (from open LIDAR, drone photogrammetry or a
ground reconstruction) and produces the numbers a roofer actually prices
from: plane pitches, TRUE sloped areas, and ridge / hip / valley lengths.

No numpy, no scipy. The heavy raster handling lives in roof.py; this is the
maths, kept dependency-free so it runs and tests anywhere.

THE ONE THING THAT MATTERS MOST: true sloped area, not plan area. A roof
covering a 50 m2 footprint at 35 degrees is 61 m2 of tiles. Pricing off the
footprint under-orders by 22% — the classic roofing estimating error, and
the reason a measured pitch is worth more than a measured outline.
"""
import math
import random

# --- segmentation defaults -------------------------------------------------
# Inlier distance for RANSAC plane fitting, in metres. Environment Agency
# LIDAR is +/-15cm vertical RMSE, so a threshold below that just fragments
# one real roof plane into several. 0.25m is a little over 1 sigma.
DEFAULT_INLIER_M = 0.25
# A roof plane smaller than this is noise, a chimney or a small dormer that
# 1m sampling cannot resolve honestly.
MIN_PLANE_POINTS = 12
# Below this the surface is flat roof, not a pitched plane.
FLAT_PITCH_DEG = 5.0
# Intersection lines within this of horizontal count as ridges, not hips.
RIDGE_TOLERANCE_DEG = 8.0


class Plane:
    """A fitted roof plane: z = a*x + b*y + c, with its supporting points."""

    def __init__(self, a, b, c, points=None):
        self.a, self.b, self.c = a, b, c
        self.points = points or []

    # -- geometry ---------------------------------------------------------
    def z_at(self, x, y):
        return self.a * x + self.b * y + self.c

    def distance(self, p):
        """Perpendicular distance from a point to the plane."""
        x, y, z = p
        return abs(z - self.z_at(x, y)) / math.sqrt(
            self.a * self.a + self.b * self.b + 1.0)

    @property
    def pitch_deg(self):
        """Angle from horizontal — what a roofer calls the pitch."""
        return math.degrees(math.atan(math.hypot(self.a, self.b)))

    @property
    def slope_factor(self):
        """Multiplier from plan area to true sloped area (1/cos(pitch))."""
        return math.sqrt(self.a * self.a + self.b * self.b + 1.0)

    @property
    def aspect_deg(self):
        """Compass bearing the roof face looks toward, 0 = north.

        Matters for solar, for which elevation faces the weather, and for
        working out which side needs scaffold.
        """
        if math.hypot(self.a, self.b) < 1e-9:
            return None  # flat: no meaningful aspect
        # Downslope direction in plan is (-a, -b); x is east, y is north.
        return math.degrees(math.atan2(-self.a, -self.b)) % 360.0

    @property
    def is_flat(self):
        return self.pitch_deg < FLAT_PITCH_DEG

    def centroid(self):
        n = len(self.points)
        if not n:
            return (0.0, 0.0, 0.0)
        return (sum(p[0] for p in self.points) / n,
                sum(p[1] for p in self.points) / n,
                sum(p[2] for p in self.points) / n)

    def plan_area(self, cell_area):
        """Plan (footprint) area of this plane, from its sample count."""
        return len(self.points) * cell_area

    def sloped_area(self, cell_area):
        """TRUE surface area — what you actually buy tiles for."""
        return self.plan_area(cell_area) * self.slope_factor

    def as_dict(self, cell_area):
        return {
            "pitch_deg": round(self.pitch_deg, 1),
            "aspect_deg": (round(self.aspect_deg, 1)
                           if self.aspect_deg is not None else None),
            "plan_area_m2": round(self.plan_area(cell_area), 2),
            "sloped_area_m2": round(self.sloped_area(cell_area), 2),
            "slope_factor": round(self.slope_factor, 4),
            "points": len(self.points),
            "flat": self.is_flat,
            "coefficients": {"a": self.a, "b": self.b, "c": self.c},
        }


def fit_plane(points):
    """Least-squares plane through >=3 points. Returns a Plane or None.

    Solves the normal equations for z = ax + by + c directly — a 3x3 system,
    small enough that Cramer's rule is clearer than bringing in a solver.

    Points are CENTRED on their own mean before fitting, then the constant
    term is shifted back. This is not a nicety: real inputs arrive in British
    National Grid coordinates around E=413000, N=289000, which makes the
    sums-of-squares terms ~1.7e11 per point. The normal equations lose all
    precision at that magnitude and the fit collapses to a horizontal plane —
    silently turning every pitched roof in the country flat, while synthetic
    tests near the origin pass happily. Live-confirmed on a Birmingham
    address before this centring was added.

    Translation changes only the constant term, so a and b — and therefore
    pitch, aspect and area — are unaffected by the shift.
    """
    n = len(points)
    if n < 3:
        return None

    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n

    sx = sy = sz = sxx = syy = sxy = sxz = syz = 0.0
    for px, py, z in points:
        x, y = px - mx, py - my
        sx += x; sy += y; sz += z
        sxx += x * x; syy += y * y; sxy += x * y
        sxz += x * z; syz += y * z

    m = [[sxx, sxy, sx],
         [sxy, syy, sy],
         [sx,  sy,  float(n)]]
    rhs = [sxz, syz, sz]

    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-12:
        # Degenerate — all points collinear in plan.
        return None

    def _solve(col):
        mm = [row[:] for row in m]
        for i in range(3):
            mm[i][col] = rhs[i]
        return (mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
                - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det

    a, b, c_centred = _solve(0), _solve(1), _solve(2)
    # Undo the centring: z = a(x-mx) + b(y-my) + c'  =>  c = c' - a*mx - b*my
    return Plane(a, b, c_centred - a * mx - b * my, list(points))


def segment_planes(points, inlier_m=DEFAULT_INLIER_M,
                   min_points=MIN_PLANE_POINTS, max_planes=12,
                   iterations=200, seed=1):
    """RANSAC segmentation of a roof point set into planes.

    Deterministic by default (fixed seed) so the same scan always yields the
    same quantities — a quote that changes between runs on identical input
    is not a quote anyone can rely on.
    """
    rng = random.Random(seed)
    remaining = list(points)
    planes = []

    while len(remaining) >= min_points and len(planes) < max_planes:
        best_plane, best_inliers = None, []
        for _ in range(iterations):
            if len(remaining) < 3:
                break
            sample = rng.sample(remaining, 3)
            candidate = fit_plane(sample)
            if candidate is None:
                continue
            # Reject near-vertical fits: a wall is not a roof plane, and a
            # steep spurious fit swallows points from real ones.
            if candidate.pitch_deg > 80.0:
                continue
            inliers = [p for p in remaining
                       if candidate.distance(p) <= inlier_m]
            if len(inliers) > len(best_inliers):
                best_plane, best_inliers = candidate, inliers

        if best_plane is None or len(best_inliers) < min_points:
            break

        # Refit on all inliers — the 3-point sample only located the plane.
        refined = fit_plane(best_inliers) or best_plane
        refined.points = best_inliers
        planes.append(refined)

        inlier_set = set(map(id, best_inliers))
        remaining = [p for p in remaining if id(p) not in inlier_set]

    planes.sort(key=lambda p: len(p.points), reverse=True)
    return planes


class Edge:
    """An intersection between two roof planes, classified as roofers name
    them: ridge, hip or valley. Each carries different materials and
    different labour."""

    def __init__(self, kind, length_m, slope_deg, planes):
        self.kind = kind
        self.length_m = length_m
        self.slope_deg = slope_deg
        self.planes = planes

    def as_dict(self):
        return {"kind": self.kind,
                "length_m": round(self.length_m, 2),
                "slope_deg": round(self.slope_deg, 1)}


def _intersection_line(p1, p2):
    """Direction and slope of the line where two planes meet.

    Returns (dir_x, dir_y, dz_per_unit) in plan coordinates, or None if the
    planes are parallel.
    """
    da, db = p1.a - p2.a, p1.b - p2.b
    mag = math.hypot(da, db)
    if mag < 1e-9:
        return None  # parallel — no intersection line
    # The line runs perpendicular to the gradient difference.
    dx, dy = -db / mag, da / mag
    dz = p1.a * dx + p1.b * dy
    return dx, dy, dz


def classify_edge(p1, p2, cell_size):
    """Classify the junction between two planes, or None if they don't meet.

    Convexity is decided from the data rather than the algebra: if each
    plane's own points sit on its own side of the intersection line, the
    surface is the LOWER of the two planes on each side, which is a convex
    junction — a ridge or a hip, shedding water. Reversed, it is concave —
    a valley, collecting it.
    """
    line = _intersection_line(p1, p2)
    if line is None:
        return None
    dx, dy, dz = line

    # Perpendicular axis in plan, along which the two planes diverge.
    px, py = -dy, dx

    c1, c2 = p1.centroid(), p2.centroid()
    # Signed positions of each plane's points along the perpendicular axis.
    s1 = c1[0] * px + c1[1] * py
    s2 = c2[0] * px + c2[1] * py
    if abs(s1 - s2) < 1e-9:
        return None  # coincident — not a real junction

    # By construction of (px, py), the height difference z1 - z2 changes at
    # rate -(da^2 + db^2)/mag along +p — always negative. So plane1 lies
    # BELOW plane2 on the +p side, and above it on the -p side.
    #
    # The real surface takes each plane where that plane's points are. If
    # plane1's points sit on the +p side (s1 > s2), the surface is taking the
    # LOWER plane on each side: it sheds away from the line, which is convex
    # — a ridge or a hip. Reversed, it takes the higher plane each side and
    # collects water: concave, a valley.
    convex = s1 > s2

    slope_deg = math.degrees(math.atan(abs(dz)))
    if convex:
        kind = "ridge" if slope_deg <= RIDGE_TOLERANCE_DEG else "hip"
    else:
        kind = "valley"

    length = _seam_extent(p1, p2, dx, dy, cell_size, mag=math.hypot(
        p1.a - p2.a, p1.b - p2.b))
    if length <= 0:
        return None
    return Edge(kind, length, slope_deg, (p1, p2))


# A junction needs this many supporting points from EACH plane before it is
# believed. Two planes always intersect somewhere in infinite space; only
# the ones with real points along the seam share a physical edge.
MIN_SEAM_POINTS = 3


def _seam_extent(p1, p2, dx, dy, cell_size, mag):
    """Length of the physical junction between two planes.

    Measures only points that actually lie NEAR the seam — where the two
    planes agree in height — rather than the overlap of their full extents.

    Without this, any two planes appear to share an edge. On a hipped roof
    the front and back slopes never touch except at the ridge, but their
    projected extents overlap completely, which invents a junction the length
    of the whole building.
    """
    if mag < 1e-9:
        return 0.0
    # A point one cell from the seam differs in height by about cell*mag.
    # Allow ~1.5 cells so a grid-sampled seam is captured without dragging in
    # the whole slope.
    tol = 1.5 * cell_size * mag

    def _near(plane):
        return [p for p in plane.points
                if abs(p1.z_at(p[0], p[1]) - p2.z_at(p[0], p[1])) <= tol]

    n1, n2 = _near(p1), _near(p2)
    if len(n1) < MIN_SEAM_POINTS or len(n2) < MIN_SEAM_POINTS:
        return 0.0  # planes meet in theory, not on this roof

    vals = [p[0] * dx + p[1] * dy for p in n1 + n2]
    # One cell of tolerance: a grid-sampled seam rarely lands on the exact
    # boundary at either end.
    return max(0.0, (max(vals) - min(vals)) + cell_size)


def find_edges(planes, cell_size):
    """Classify every junction between the given planes."""
    edges = []
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            if planes[i].is_flat and planes[j].is_flat:
                continue
            edge = classify_edge(planes[i], planes[j], cell_size)
            if edge is not None:
                edges.append(edge)
    return edges


# --- materials -------------------------------------------------------------
# UK defaults. Every figure is overridable — a roofer's own gauges and
# waste allowances beat any table, exactly as with the rate card.
MATERIAL_DEFAULTS = {
    "covering": "concrete_interlocking",
    "coverings": {
        # units per m2 of TRUE sloped area, and batten run in m per m2
        "concrete_interlocking": {"units_per_m2": 10.0, "batten_m_per_m2": 3.33},
        "plain_tile":            {"units_per_m2": 60.0, "batten_m_per_m2": 10.0},
        "natural_slate":         {"units_per_m2": 20.0, "batten_m_per_m2": 4.5},
    },
    "membrane_overlap_factor": 1.15,   # laps and cutting
    "ridge_units_per_m": 3.33,         # 300mm effective ridge tile
    "waste_factor": 1.10,              # cuts, breakages, hips and valleys
}


def quantities(planes, edges, cell_area, cell_size, eaves_length_m=None,
               materials=None, footprint_area_m2=None):
    """Roof takeoff — the numbers that go into a quote.

    Everything derives from TRUE sloped area, never plan area.

    `footprint_area_m2`, when given, is the authoritative plan area and the
    per-plane areas are apportioned to match it by their share of samples.
    Two reasons this beats counting cells: a 1m grid quantises the outline
    and gains or loses up to half a metre all the way round, and samples
    near the wall line are dropped before fitting, so the surviving count
    covers less than the real roof.
    """
    cfg = dict(MATERIAL_DEFAULTS)
    if materials:
        cfg.update(materials)

    covering = cfg["covering"]
    spec = cfg["coverings"].get(covering)
    if spec is None:
        raise ValueError(
            f"unknown covering {covering!r}; known: "
            f"{', '.join(cfg['coverings'])}")

    sampled_plan = sum(p.plan_area(cell_area) for p in planes)
    if footprint_area_m2 and sampled_plan > 0:
        scale = footprint_area_m2 / sampled_plan
        plan = footprint_area_m2
        # Each plane keeps its own slope factor; only the area is rescaled.
        sloped = sum(p.plan_area(cell_area) * scale * p.slope_factor
                     for p in planes)
    else:
        scale = 1.0
        plan = sampled_plan
        sloped = sum(p.sloped_area(cell_area) for p in planes)
    waste = cfg["waste_factor"]

    by_kind = {"ridge": 0.0, "hip": 0.0, "valley": 0.0}
    for e in edges:
        by_kind[e.kind] = by_kind.get(e.kind, 0.0) + e.length_m

    pitched = [p for p in planes if not p.is_flat]
    pitch_values = [p.pitch_deg for p in pitched]

    return {
        "plan_area_m2": round(plan, 2),
        "sloped_area_m2": round(sloped, 2),
        "plan_area_source": ("footprint_polygon" if footprint_area_m2
                             else "sampled_cells"),
        "sampled_plan_area_m2": round(sampled_plan, 2),
        # The number that stops the classic under-order.
        "slope_uplift_pct": (round((sloped / plan - 1) * 100, 1)
                             if plan > 0 else 0.0),
        "predominant_pitch_deg": (round(max(set(round(v) for v in pitch_values),
                                            key=lambda v: sum(
                                                1 for x in pitch_values
                                                if round(x) == v)), 1)
                                  if pitch_values else None),
        "plane_count": len(planes),
        "flat_area_m2": round(sum(p.plan_area(cell_area) * scale
                                  * p.slope_factor
                                  for p in planes if p.is_flat), 2),
        "ridge_m": round(by_kind.get("ridge", 0.0), 2),
        "hip_m": round(by_kind.get("hip", 0.0), 2),
        "valley_m": round(by_kind.get("valley", 0.0), 2),
        "eaves_m": (round(eaves_length_m, 2)
                    if eaves_length_m is not None else None),
        "materials": {
            "covering": covering,
            "covering_units": math.ceil(sloped * spec["units_per_m2"] * waste),
            "battens_m": round(sloped * spec["batten_m_per_m2"] * waste, 1),
            "membrane_m2": round(sloped * cfg["membrane_overlap_factor"], 1),
            "ridge_units": math.ceil(
                (by_kind.get("ridge", 0.0) + by_kind.get("hip", 0.0))
                * cfg["ridge_units_per_m"] * waste),
            "valley_m": round(by_kind.get("valley", 0.0) * waste, 1),
            "guttering_m": (round(eaves_length_m, 1)
                            if eaves_length_m is not None else None),
            "waste_factor": waste,
        },
    }


def pitch_uncertainty_deg(vertical_rmse_m, run_m):
    """How well pitch can be known, given the source data's vertical error.

    At +/-15cm RMSE (Environment Agency LIDAR) over a 4m rafter run, pitch
    is good to roughly +/-3 degrees. Over a 2m run it is +/-6 — which is why
    small dormers and porches should be reported as low-confidence rather
    than quoted from. Reported alongside every result: a pitch without an
    error bar invites someone to order tiles against it.
    """
    if run_m <= 0:
        return None
    # Worst case: error of opposite sign at each end of the run.
    return round(math.degrees(math.atan(2 * vertical_rmse_m / run_m)), 1)
