"""Register Mode — align two scans of the same place.

The last mechanical piece of the X-ray. Services are recorded in the OPEN
scan's coordinates, taken at first fix. The finished wall the builder is
standing in front of is the CLOSED scan. Registration is what puts the
recorded pipe onto the wall he is about to drill.

THE STAKE IS DIFFERENT HERE. Everywhere else in this worker a bad answer
costs money — a wrong quantity, an over-ordered pallet of tiles. A bad
registration puts a live cable 200mm from where the app says it is, and
somebody drills there. So this module is built to refuse: a fit it cannot
verify is reported as a failure, never as a best effort.

THREE DEGREES OF FREEDOM, NOT SIX, and that is a real simplification rather
than a shortcut. Both scans are gravity-aligned — structure.py enforces it
and refuses otherwise — so the floor is level in both and the only unknowns
are translation in x, y, z and yaw about the vertical. Solving 3-DOF has a
closed form, converges from a poor start, and cannot silently tip a building
over the way a full 6-DOF fit can when it lands in a local minimum.

Pure stdlib. No SVD, no numpy, no Open3D — the 2D Procrustes rotation is
atan2 of two sums.
"""
import math
import os

# --- what counts as aligned ------------------------------------------------

# Inlier distance. Two scans of the same room, correctly aligned, should have
# most points within a couple of centimetres of a neighbour — that is roughly
# phone-LiDAR noise plus the plaster thickness that genuinely differs between
# an open and a closed scan.
INLIER_M = 0.03

# Below this share of matched points the fit is not describing the same room.
MIN_INLIER_RATIO = 0.35

# Above this RMSE the fit is too loose to drill on, whatever the ratio says.
MAX_RMSE_M = 0.025

# A registration good enough to position services on a wall.
GOOD_RMSE_M = 0.012
GOOD_INLIER_RATIO = 0.60

MAX_ITERATIONS = 25
CONVERGED_M = 1e-5
CONVERGED_RAD = 1e-6

# Search radii, widest first. ICP only converges when its correspondences are
# mostly right, and at the start they are not — so it begins wide enough to
# tolerate a poor initial yaw and tightens onto the real inlier distance.
# Polishing radii after the yaw is already square. Much tighter than a
# blind coarse-to-fine sweep needs to be, because the rotation is solved
# globally before ICP starts rather than by ICP itself.
POLISH_SCHEDULE = (0.15, 0.06)

# Roughly how many points a coarse level works with, and how many iterations
# it gets. A wide radius means a coarse grid, a coarse grid means crowded
# buckets, and crowded buckets make every lookup expensive — so a coarse pass
# over every point is both slow and pointless. Early levels only have to
# recover a rough yaw, and a few hundred points do that as well as ten
# thousand.
COARSE_SAMPLE = 400
COARSE_ITERATIONS = 12

# Most points a fit ever works with. A rigid 3-DOF transform has three
# unknowns; a few thousand well-spread points determine it as precisely as a
# hundred thousand do, and the extra only costs time — every additional point
# is another 27-bucket neighbour lookup on every iteration. Open3D subsamples
# before ICP for exactly this reason.
MAX_ALIGN_POINTS = 3000

# Cell size for the spatial hash used to find neighbours.
GRID_M = 0.05


class RegistrationError(ValueError):
    """Raised when two scans cannot be aligned trustworthily.

    Deliberately fatal, and more so than elsewhere in this worker. A wrong
    quantity costs money; a wrong registration is why somebody drills into a
    live cable.
    """


# --- transforms ------------------------------------------------------------

class Transform:
    """Yaw about the vertical plus a translation. The whole rigid motion
    available to two gravity-aligned scans of the same room."""

    def __init__(self, yaw=0.0, tx=0.0, ty=0.0, tz=0.0):
        self.yaw = float(yaw)
        self.tx, self.ty, self.tz = float(tx), float(ty), float(tz)

    def apply(self, points):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return [(x * c - y * s + self.tx,
                 x * s + y * c + self.ty,
                 z + self.tz) for x, y, z in points]

    def then(self, other):
        """This transform followed by another, as one transform."""
        c, s = math.cos(other.yaw), math.sin(other.yaw)
        return Transform(
            self.yaw + other.yaw,
            self.tx * c - self.ty * s + other.tx,
            self.tx * s + self.ty * c + other.ty,
            self.tz + other.tz)

    def as_dict(self):
        # Signed, in (-180, 180]. A registration correction is a small angle
        # either side of zero, and reporting the same -12 degree correction
        # as 348 is technically true and useless: it reads as most of a full
        # turn, and nobody eyeballing a fit can tell 348 from a failure.
        degrees = (math.degrees(self.yaw) + 180.0) % 360.0 - 180.0
        return {
            "yaw_deg": round(degrees, 4),
            "translation_m": [round(self.tx, 4), round(self.ty, 4),
                              round(self.tz, 4)],
        }


def centroid(points):
    if not points:
        raise RegistrationError("no points to take a centroid of")
    n = len(points)
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


# --- neighbour lookup ------------------------------------------------------

class Grid:
    """Spatial hash. Nearest-neighbour lookup without a KD-tree.

    A KD-tree would be tidier and needs either a dependency or a hundred
    lines. A hash grid is fifteen, and for uniformly-sampled scan data at a
    known noise scale it is just as fast — the cell size IS the search
    radius, so a lookup touches 27 cells and stops.
    """

    def __init__(self, points, cell_m=GRID_M):
        self.cell = cell_m
        self.buckets = {}
        for p in points:
            self.buckets.setdefault(self._key(p), []).append(p)

    def _key(self, p):
        return (int(math.floor(p[0] / self.cell)),
                int(math.floor(p[1] / self.cell)),
                int(math.floor(p[2] / self.cell)))

    def nearest(self, point, max_distance):
        kx, ky, kz = self._key(point)
        best, best_d2 = None, max_distance * max_distance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in self.buckets.get((kx + dx, ky + dy, kz + dz), ()):
                        d2 = ((q[0] - point[0]) ** 2 + (q[1] - point[1]) ** 2
                              + (q[2] - point[2]) ** 2)
                        if d2 < best_d2:
                            best, best_d2 = q, d2
        return best, math.sqrt(best_d2) if best else None


# --- the fit ---------------------------------------------------------------

def solve_step(pairs):
    """Best yaw and translation taking source points onto target points.

    Closed form. In 2D the optimal rotation is
        theta = atan2( sum(sx*ty - sy*tx), sum(sx*tx + sy*ty) )
    on centred coordinates — the same Procrustes result an SVD would give,
    without needing one. Height is a straight mean offset, because both
    clouds are already level.
    """
    if not pairs:
        raise RegistrationError("no correspondences to solve from")

    source = [s for s, _t in pairs]
    target = [t for _s, t in pairs]
    cs, ct = centroid(source), centroid(target)

    num = den = 0.0
    for (sx, sy, _sz), (tx, ty, _tz) in pairs:
        ax, ay = sx - cs[0], sy - cs[1]
        bx, by = tx - ct[0], ty - ct[1]
        num += ax * by - ay * bx
        den += ax * bx + ay * by

    yaw = math.atan2(num, den)
    c, s = math.cos(yaw), math.sin(yaw)
    return Transform(
        yaw,
        ct[0] - (cs[0] * c - cs[1] * s),
        ct[1] - (cs[0] * s + cs[1] * c),
        ct[2] - cs[2])


def score(source, grid, inlier_m=INLIER_M):
    """How well a transformed cloud sits on the target."""
    if not source:
        raise RegistrationError("nothing to score")
    total = 0.0
    inliers = 0
    for p in source:
        _q, d = grid.nearest(p, inlier_m)
        if d is not None:
            inliers += 1
            total += d * d
    ratio = inliers / len(source)
    rmse = math.sqrt(total / inliers) if inliers else float("inf")
    # A truncated least-squares cost over EVERY source point, counting a
    # point with no neighbour at the full inlier distance. This is what ICP
    # actually minimises, and unlike "ratio, then RMSE" it moves smoothly:
    # comparing ratio first makes the accept-test brittle, because a step
    # that clearly improves the geometry can nudge one point over the inlier
    # boundary and be rejected for it.
    cost = total + (len(source) - inliers) * inlier_m * inlier_m
    return {"inlier_ratio": round(ratio, 4),
            "rmse_m": round(rmse, 5) if inliers else None,
            "cost": cost,
            "inliers": inliers, "points": len(source)}


def principal_yaw(points, step_deg=0.5, sample=1500):
    """The yaw that squares a building up with the axes.

    ICP alone is a poor way to recover this. Point-to-point ICP slides on
    flat surfaces — a wall can slide along itself without the error changing
    at all — so on a room made mostly of large flat planes it converges
    slowly and stops short, leaving a degree or two of yaw behind. A degree
    of yaw is 50mm at the far end of a 3m wall, which is exactly the error
    this module exists to prevent.

    Buildings offer a much stronger prior: they are Manhattan. Walls meet at
    right angles, so the plan-view bounding box is smallest when the building
    is square with the axes. Sweeping the angle and taking the minimum is a
    GLOBAL estimate — it cannot slide into a local minimum, because it does
    not descend anything.

    Returns a yaw in [0, pi/2). The four-fold ambiguity of a rectangle is
    resolved by align(), which tries all four and keeps the best fit.
    """
    if not points:
        raise RegistrationError("no points to take an orientation from")
    if len(points) > sample:
        points = points[::max(1, len(points) // sample)]

    def area_at(angle):
        c, s = math.cos(angle), math.sin(angle)
        xs = [p[0] * c - p[1] * s for p in points]
        ys = [p[0] * s + p[1] * c for p in points]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    best_angle, best_area = 0.0, None
    for i in range(int(90.0 / step_deg)):
        angle = math.radians(i * step_deg)
        area = area_at(angle)
        if best_area is None or area < best_area:
            best_angle, best_area = angle, area

    # REFINE. The sweep's resolution IS the yaw error, and yaw error grows
    # with distance from the centre: half a degree is 26mm at the far end of
    # a 3m wall, which on its own exceeds the tolerance this module demands.
    # A local sweep at fine resolution costs almost nothing and takes that
    # to about a millimetre.
    span = math.radians(step_deg)
    for _ in range(4):
        span /= 5.0
        for i in range(-5, 6):
            angle = best_angle + i * span
            area = area_at(angle)
            if area < best_area:
                best_angle, best_area = angle, area
    return best_angle


def _better(candidate, incumbent):
    """Lower truncated least-squares cost. See score() for why not ratio."""
    return candidate["cost"] < incumbent["cost"]


def _thin(points, target_count):
    """A bounded, evenly-spread subset. DELIBERATELY NOT A STRIDE.

    This one line is why the module did not work for a fortnight.

    A stride assumes the cloud's order carries no structure. It always does:
    a PLY is written in whatever order the producer chose, and a room
    generator that appends wall points in pairs — (i, 0) then (i, depth) —
    puts one wall on even indices and its opposite on odd. An even stride
    then keeps one member of every pair forever, which deleted TWO OF THE
    FOUR WALLS:

        full   {x=0: 2758, x=5: 2758, y=0: 3518, y=4: 3276}
        [::6]  {x=0:  896, x=5:   24, y=0: 1132, y=4:    0}

    Half a room has a different centroid from a whole one — 0.72m different
    here, five times the widest polish radius — so the centroid start landed
    somewhere ICP could never walk back from. It presented as "the two scans
    do not align", and the fault was in the sampler, not the alignment.

    The comment two lines below this call has always warned about exactly
    this hazard, and applied the lesson only to the target.

    A seeded shuffle cannot correlate with write order however the cloud was
    written, and being seeded it stays reproducible: the same pair of scans
    always aligns the same way, which matters when someone re-runs a job to
    check a measurement they are about to drill against.
    """
    import random
    return random.Random(0).sample(points, target_count)


def align(source, target, inlier_m=INLIER_M, max_iterations=MAX_ITERATIONS):
    """Iterative closest point, 3-DOF, from a centroid start.

    Returns the transform taking SOURCE into TARGET's frame, and its score.
    Does not judge whether the result is usable — verify() does that, and
    keeping the two apart means a caller cannot accidentally use a fit
    nobody checked.
    """
    if not source or not target:
        raise RegistrationError("both scans need points to align")

    # Work with a bounded, evenly-spread subset — see _thin, which is where
    # this went wrong. A prefix of a scan is one wall, and a fit computed
    # from one wall is free to slide along it; a STRIDE of a scan can be two
    # walls of four, which is worse, because it still looks like a room.
    #
    # Centroid and principal yaw come from the FULL cloud, before thinning.
    # Both are O(n) single passes, so there is nothing to save by computing
    # them from the subset — and computing them from the subset costs
    # accuracy: the centroid of 3000 samples of an 18000-point room differs
    # from the true centroid by sampling noise, which lands the ICP
    # initialisation ~14mm out and leaves it there.
    cs, ct = centroid(source), centroid(target)
    yaw_source = principal_yaw(source)

    if len(source) > MAX_ALIGN_POINTS:
        source = _thin(source, MAX_ALIGN_POINTS)
    # The TARGET is never thinned. Only the source costs time — it drives the
    # lookups — while the target only costs memory in the grid, and a denser
    # target strictly improves every correspondence. Thinning it was actively
    # harmful: a point cloud is written in a structured order, so striding it
    # decimates along one axis rather than sampling evenly, and the surviving
    # points end up further from where a source point actually lands.

    grid = Grid(target, max(inlier_m, GRID_M))

    # Square both scans up first, then let ICP polish. A rectangle looks the
    # same rotated by 90 degrees, so all four are tried and scored — cheap,
    # and it removes the one failure mode a global yaw estimate has.
    base = yaw_source - principal_yaw(target)

    best = None
    for quarter in range(4):
        yaw = base + quarter * math.pi / 2.0
        c, s_ = math.cos(yaw), math.sin(yaw)
        transform = Transform(
            yaw,
            ct[0] - (cs[0] * c - cs[1] * s_),
            ct[1] - (cs[0] * s_ + cs[1] * c),
            ct[2] - cs[2])
        moved = transform.apply(source)
        iterations = 0
        current = score(moved, grid, inlier_m)

        for radius in [r for r in POLISH_SCHEDULE if r > inlier_m] + [inlier_m]:
            level_grid = Grid(target, max(radius, GRID_M))
            for _ in range(max_iterations):
                iterations += 1
                pairs = []
                for p in moved:
                    q, d = level_grid.nearest(p, radius)
                    if q is not None:
                        pairs.append((p, q))
                if len(pairs) < 3:
                    break

                step = solve_step(pairs)
                candidate = step.apply(moved)
                scored = score(candidate, grid, inlier_m)

                # ONLY ACCEPT AN IMPROVEMENT. Point-to-point ICP slides on
                # flat surfaces, and a room is mostly flat surfaces — left
                # unchecked it will happily walk away from a good global
                # alignment into a worse one that still reduces its own
                # local objective. The global yaw estimate is usually
                # already close, so ICP's job here is to polish or do
                # nothing, never to undo.
                if not _better(scored, current):
                    break
                transform = transform.then(step)
                moved, current = candidate, scored

                if (abs(step.yaw) < CONVERGED_RAD
                        and abs(step.tx) < CONVERGED_M
                        and abs(step.ty) < CONVERGED_M
                        and abs(step.tz) < CONVERGED_M):
                    break

        result = dict(current, iterations=iterations)
        if best is None or result["cost"] < best[0]:
            best = (result["cost"], transform, result)

    return best[1], best[2]


def verify(result):
    """Decide whether a fit may be used to position services.

    Separate from align() on purpose. Alignment always produces a number;
    only this says whether the number means anything, and it is the gate a
    caller has to pass to put a pipe on a wall.
    """
    ratio = result.get("inlier_ratio") or 0.0
    rmse = result.get("rmse_m")

    if rmse is None or ratio < MIN_INLIER_RATIO:
        raise RegistrationError(
            f"these two scans do not align: only {ratio * 100:.0f}% of points "
            f"found a match within {INLIER_M * 1000:.0f}mm. They are probably "
            f"not the same room, or one of them is not gravity-aligned. "
            f"Services must NOT be positioned from this.")
    if rmse > MAX_RMSE_M:
        raise RegistrationError(
            f"alignment is too loose to drill on: {rmse * 1000:.0f}mm RMSE "
            f"against a {MAX_RMSE_M * 1000:.0f}mm limit. A pipe positioned "
            f"from this could be that far from where it really is. Re-scan "
            f"with more overlap between the two captures.")

    good = rmse <= GOOD_RMSE_M and ratio >= GOOD_INLIER_RATIO
    return {
        "usable": True,
        "confidence": "good" if good else "fair",
        "rmse_mm": round(rmse * 1000, 1),
        "inlier_ratio": ratio,
        "note": (
            f"Aligned to {rmse * 1000:.0f}mm RMSE with "
            f"{ratio * 100:.0f}% of points matched."
            + ("" if good else
               " Treat positions as indicative and verify with a detector "
               "before drilling.")),
    }


def register(source, target, inlier_m=INLIER_M):
    """Align and verify in one call. Raises unless the fit is usable."""
    transform, result = align(source, target, inlier_m)
    verdict = verify(result)
    return {
        "transform": transform.as_dict(),
        "fit": result,
        "verdict": verdict,
        "warnings": [
            "Registration assumes both scans are gravity-aligned — the same "
            "assumption structure mode enforces. A tilted scan will align to "
            "a plausible-looking wrong answer.",
            "Positions carried across a registration are only as good as the "
            "fit. Always use a detector before drilling.",
        ],
    }


# --- handler entry point ---------------------------------------------------

def run(spec, prog, output_dir):
    """Register mode entry point.

    Takes the OPEN scan as source and the CLOSED scan as target, because the
    services live in the open scan's frame and the wall the builder is
    standing at is the closed one.
    """
    import json
    import paths
    import structure

    prog.stage("fetching")
    source_path = spec.get("point_cloud_path") or spec.get("point_cloud_url")
    target_path = spec.get("registration_target_path") or spec.get(
        "registration_target")
    if not source_path or not target_path:
        raise RegistrationError(
            "register mode needs two scans: the open scan as point_cloud_url "
            "and the closed scan as registration_target.")

    def load(path, label):
        if os.path.exists(path):
            return structure.read_ply(path)
        import validation
        # fetch_checked, NOT check_fetchable_url + requests.get. The check
        # guards the first hop only, and requests follows redirects by
        # default: a public host that passes the check can answer
        # 302 Location: http://169.254.169.254/... and the worker fetches
        # the cloud metadata service. Every other module that takes a
        # caller-supplied URL was moved onto fetch_checked; register kept
        # the old pattern while it was parked, and carried it into being a
        # live dispatchable mode.
        local = os.path.join(paths.ensure(output_dir), f"{label}.ply")
        response = validation.fetch_checked(path, field=f"{label} cloud URL",
                                            timeout=600, stream=True)
        response.raise_for_status()
        with open(local, "wb") as f:
            for chunk in response.iter_content(1 << 20):
                f.write(chunk)
        return structure.read_ply(local)

    source = load(source_path, "open")
    target = load(target_path, "closed")

    prog.stage("coarse_align")
    voxel = spec.get("voxel_m") or 0.03
    source = structure.voxel_downsample(source, voxel)
    target = structure.voxel_downsample(target, voxel)

    prog.stage("icp")
    transform, fit = align(source, target)

    prog.stage("scoring")
    result = {"transform": transform.as_dict(), "fit": fit,
              "points": {"open": len(source), "closed": len(target)}}
    try:
        result["verdict"] = verify(fit)
        result["warnings"] = register.__doc__ and []
    except RegistrationError as e:
        # Report the failure with its numbers rather than raising: the fit
        # statistics are exactly what tells a user how to re-scan.
        result["verdict"] = {"usable": False, "reason": str(e)}
    result["warnings"] = [
        "Registration assumes both scans are gravity-aligned. A tilted scan "
        "will align to a plausible-looking wrong answer.",
        "Always use a detector before drilling, whatever this says.",
    ]

    prog.stage("exporting")
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "registration"
    path = os.path.join(directory, f"{scan}.registration.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    return ([(path, f"registrations/{scan}.json", None)],
            {"registration": result, "warnings": result["warnings"]})
