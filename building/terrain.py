"""Site levels, earthworks and landscape from terrain data.

Named terrain rather than site because `site` is a Python standard
library module — `import site` silently picks up the stdlib one and
every function here goes missing.

Roof Mode already fetches a terrain model to subtract ground from surface.
That same data answers a set of questions a builder needs before anything is
priced: which way the ground falls, whether the plot needs terracing, where
water goes, how deep foundations have to be, and whether a level platform
means importing fill or carting muck away.

Same discipline as regs.py and safety.py: cite the source, carry the
measurement uncertainty, and say plainly what the data cannot see.

WHAT TERRAIN DATA CANNOT TELL YOU, and this module says so rather than
implying otherwise: soil type, bearing capacity, water table, existing
drains, services, made ground, or contamination. Foundation depth advice
here is a planning figure from tree proximity and slope — it is not a
substitute for trial holes, and on clay with trees the difference between
the two can be a metre of concrete.
"""
import math

PASS = "pass"
ATTENTION = "attention"
UNKNOWN = "insufficient_data"

CRITICAL = "critical"
MAJOR = "major"
ADVISORY = "advisory"

# --- slope thresholds ------------------------------------------------------
# Expressed as gradients because that is how drainage and groundworks are
# actually discussed on site.
SLOPE_FLAT = 1 / 40      # 1.43deg — below this, surface drainage needs care
SLOPE_MODERATE = 1 / 20  # 2.86deg — affects levels and thresholds
SLOPE_STEEP = 1 / 10     # 5.71deg — terracing or retaining likely
SLOPE_SEVERE = 1 / 5     # 11.3deg — split-level or stepped foundations

# --- drainage --------------------------------------------------------------
# Approved Document H: minimum falls for foul drainage.
MIN_FALL_100MM = 1 / 80    # 100mm foul drain, with care
PREFERRED_FALL_100MM = 1 / 40
MIN_FALL_150MM = 1 / 150
# A soakaway must sit clear of foundations, and of the boundary.
SOAKAWAY_MIN_FROM_BUILDING_M = 5.0

# --- foundations -----------------------------------------------------------
# Minimum trench fill depth in normal ground, before any tree influence.
MIN_FOUNDATION_DEPTH_M = 0.450
# On shrinkable clay, depth rises with proximity to trees. These are
# planning figures from the NHBC approach: the governing inputs are the
# tree's mature height, its water demand, and the clay's shrinkage
# potential. A real depth comes from trial holes and a plasticity index.
CLAY_MIN_DEPTH_M = 0.750
# Water demand by broad species group, used to scale influence distance.
TREE_WATER_DEMAND = {
    "high": 1.25,     # oak, poplar, willow, elm, eucalyptus
    "moderate": 1.0,  # ash, beech, cherry, sycamore, lime
    "low": 0.75,      # birch, holly, magnolia, most conifers
}


class Finding:
    """One site conclusion, with what it is based on."""

    def __init__(self, code, title, verdict, severity, message,
                 citation, measured=None, unit=None):
        self.code = code
        self.title = title
        self.verdict = verdict
        self.severity = severity
        self.message = message
        self.citation = citation
        self.measured = measured
        self.unit = unit

    def as_dict(self):
        d = {"code": self.code, "title": self.title, "verdict": self.verdict,
             "severity": self.severity, "message": self.message,
             "citation": self.citation}
        if self.measured is not None:
            d["measured"] = round(self.measured, 3)
            d["unit"] = self.unit
        return d


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def fit_ground_plane(points):
    """Least-squares plane through terrain points: z = ax + by + c.

    Centred before solving, for the same reason the roof fitter is — real
    inputs arrive in National Grid coordinates around E=413000, where the
    normal equations lose all precision and the fit collapses to horizontal.
    """
    n = len(points)
    if n < 3:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n

    sxx = syy = sxy = sxz = syz = sz = sx = sy = 0.0
    for px, py, z in points:
        x, y = px - mx, py - my
        sxx += x * x; syy += y * y; sxy += x * y
        sxz += x * z; syz += y * z
        sz += z; sx += x; sy += y

    m = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    rhs = [sxz, syz, sz]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-12:
        return None

    def solve(col):
        mm = [row[:] for row in m]
        for i in range(3):
            mm[i][col] = rhs[i]
        return (mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
                - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det

    a, b = solve(0), solve(1)
    return a, b, solve(2) - a * mx - b * my


def levels(points):
    """Slope, fall and drainage direction across a set of terrain points."""
    if not points or len(points) < 3:
        return None
    plane = fit_ground_plane(points)
    if plane is None:
        return None
    a, b, _ = plane

    gradient = math.hypot(a, b)
    slope_deg = math.degrees(math.atan(gradient))
    # Water runs downhill: the descent direction in plan is (-a, -b).
    fall_bearing = (math.degrees(math.atan2(-a, -b)) % 360.0
                    if gradient > 1e-9 else None)

    zs = [p[2] for p in points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    extent = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1e-6)

    return {
        "slope_deg": round(slope_deg, 2),
        "gradient": round(gradient, 4),
        "gradient_ratio": (f"1:{round(1 / gradient)}" if gradient > 1e-6
                           else "level"),
        "fall_bearing_deg": (round(fall_bearing, 1)
                             if fall_bearing is not None else None),
        "highest_m": round(max(zs), 2),
        "lowest_m": round(min(zs), 2),
        "total_fall_m": round(max(zs) - min(zs), 2),
        "extent_m": round(extent, 1),
        "points": len(points),
    }


def cut_and_fill(points, platform_level_m, cell_area_m2=1.0):
    """Volumes to bring a site to one level.

    Muck away and imported fill are priced separately and cart very
    differently, so they are reported separately rather than netted off —
    a balanced site still needs both movements paid for.
    """
    if not points:
        return None
    cut = fill = 0.0
    for _, _, z in points:
        d = z - platform_level_m
        if d > 0:
            cut += d * cell_area_m2
        else:
            fill += -d * cell_area_m2
    return {
        "platform_level_m": round(platform_level_m, 2),
        "cut_m3": round(cut, 1),
        "fill_m3": round(fill, 1),
        # Excavated ground bulks up when dug — roughly 25% for clay and
        # granular soils, which is what the grab lorry actually carts.
        "cut_bulked_m3": round(cut * 1.25, 1),
        "net_m3": round(cut - fill, 1),
        "balanced": abs(cut - fill) < max(cut, fill, 1.0) * 0.15,
    }


def balance_level(points):
    """The platform level that most nearly balances cut against fill."""
    if not points:
        return None
    return round(sum(p[2] for p in points) / len(points), 2)


# ---------------------------------------------------------------------------
# Foundations near trees
# ---------------------------------------------------------------------------

def foundation_depth(distance_m, mature_height_m, water_demand="moderate",
                     clay=True):
    """Planning depth for a foundation near a tree on shrinkable clay.

    Clay shrinks as roots draw water out, and the movement is seasonal, so a
    foundation too shallow near a thirsty tree cracks a building years after
    it is finished. Depth is driven by how close the tree is relative to its
    MATURE height — not its height today, which is the mistake that gets
    made when a sapling is standing next to a new extension.
    """
    if not clay:
        return {"depth_m": MIN_FOUNDATION_DEPTH_M, "governed_by": "normal ground",
                "note": "No shrinkable clay assumed. Trial holes still decide."}

    if distance_m is None or not mature_height_m:
        return {"depth_m": CLAY_MIN_DEPTH_M, "governed_by": "clay minimum",
                "note": "No tree data. Clay minimum applied; a nearby tree "
                        "would increase this."}

    factor = TREE_WATER_DEMAND.get(water_demand, 1.0)
    # Influence falls off with distance measured in mature tree heights.
    ratio = distance_m / (mature_height_m * factor)

    if ratio >= 1.25:
        depth = CLAY_MIN_DEPTH_M
        governed = "clay minimum, outside tree influence"
    else:
        # Deepen toward ~2.5m as the tree gets closer relative to its height.
        depth = CLAY_MIN_DEPTH_M + (2.50 - CLAY_MIN_DEPTH_M) * (1.25 - ratio) / 1.25
        governed = f"{water_demand} water-demand tree at {distance_m:.1f}m"

    return {
        "depth_m": round(min(depth, 3.0), 2),
        "governed_by": governed,
        "distance_ratio": round(ratio, 2),
        "note": "A PLANNING figure from proximity and species group. Actual "
                "depth comes from trial holes and a plasticity index, and on "
                "clay with trees the difference can be a metre of concrete. "
                "Heave precautions may also be needed where a tree is removed.",
    }


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def check_site(level_info, drainage_target_m=None, trees=None, clay=False):
    """Turn measured levels into things a builder needs to decide."""
    findings = []
    if not level_info:
        return [Finding("levels_unknown", "Site levels", UNKNOWN, None,
                        "No terrain data, so levels could not be assessed.",
                        "EA National LIDAR terrain model")]

    g = level_info["gradient"]
    ratio = level_info["gradient_ratio"]
    fall = level_info["total_fall_m"]

    if g >= SLOPE_SEVERE:
        findings.append(Finding(
            "slope", "Severe slope", ATTENTION, CRITICAL,
            f"The ground falls at {ratio} ({level_info['slope_deg']}°), "
            f"{fall}m across the site. Expect split-level or stepped "
            f"foundations, retaining structures, and a significant "
            f"groundworks cost that a flat-site rate will not cover.",
            "EA terrain model", level_info["slope_deg"], "deg"))
    elif g >= SLOPE_STEEP:
        findings.append(Finding(
            "slope", "Steep slope", ATTENTION, MAJOR,
            f"The ground falls at {ratio}, {fall}m across the site. "
            f"Terracing or a retaining wall is likely, and thresholds and "
            f"access need designing rather than assuming.",
            "EA terrain model", level_info["slope_deg"], "deg"))
    elif g >= SLOPE_MODERATE:
        findings.append(Finding(
            "slope", "Moderate slope", ATTENTION, ADVISORY,
            f"The ground falls at {ratio}, {fall}m across the site. Levels "
            f"and thresholds need setting out deliberately, but no retaining "
            f"work is implied.", "EA terrain model",
            level_info["slope_deg"], "deg"))
    elif g >= SLOPE_FLAT:
        # Between the drainage minimum and the point levels start to matter.
        # Reporting this as "near level" would be wrong in the one way that
        # costs money: at 1:40 or steeper, surface water DOES shed, and
        # telling a builder to build in falls they already have is noise.
        findings.append(Finding(
            "slope", "Gentle slope", PASS, None,
            f"The ground falls at {ratio}, {fall}m across the site — enough "
            f"to shed surface water naturally, and not enough to complicate "
            f"levels.", "EA terrain model", level_info["slope_deg"], "deg"))
    else:
        findings.append(Finding(
            "slope", "Near-level site", ATTENTION, ADVISORY,
            f"The ground is close to level at {ratio}, below the 1:40 that "
            f"sheds surface water. Falls must be built into paving and "
            f"drainage rather than relied upon, and ponding is the usual "
            f"complaint afterwards.", "EA terrain model",
            level_info["slope_deg"], "deg"))

    if level_info["fall_bearing_deg"] is not None:
        findings.append(Finding(
            "drainage_direction", "Natural fall direction", PASS, None,
            f"Ground falls toward {_compass(level_info['fall_bearing_deg'])} "
            f"({level_info['fall_bearing_deg']}°). Surface water runs that "
            f"way, so soakaways, gullies and any new hard standing should "
            f"work with it, not against it.",
            "EA terrain model", level_info["fall_bearing_deg"], "deg"))

    # Foul drainage needs fall to the connection point.
    if drainage_target_m is not None:
        available = level_info["lowest_m"] - drainage_target_m
        run = level_info["extent_m"]
        if run > 0:
            achievable = available / run
            if achievable < MIN_FALL_100MM:
                findings.append(Finding(
                    "foul_fall", "Insufficient fall to the connection",
                    ATTENTION, CRITICAL,
                    f"Only {available:.2f}m of fall is available over a "
                    f"{run:.0f}m run, about 1:{max(round(1 / achievable), 1) if achievable > 0 else '∞'}. "
                    f"A 100mm foul drain wants at least 1:80. A pumped "
                    f"station may be unavoidable — price it in now, not "
                    f"after the dig.",
                    "Approved Document H, table 5"))
            elif achievable < PREFERRED_FALL_100MM:
                findings.append(Finding(
                    "foul_fall", "Fall is tight but workable", ATTENTION,
                    MAJOR,
                    f"About 1:{round(1 / achievable)} available. Above the "
                    f"1:80 minimum for 100mm but below the 1:40 preferred, "
                    f"so laying tolerance matters and the invert levels want "
                    f"checking before anything is dug.",
                    "Approved Document H, table 5"))
            else:
                findings.append(Finding(
                    "foul_fall", "Adequate drainage fall", PASS, None,
                    f"About 1:{round(1 / achievable)} available over "
                    f"{run:.0f}m — comfortable for a 100mm foul drain.",
                    "Approved Document H, table 5"))

    for tree in (trees or []):
        depth = foundation_depth(tree.get("distance_m"),
                                 tree.get("mature_height_m"),
                                 tree.get("water_demand", "moderate"),
                                 clay=clay)
        if depth["depth_m"] > MIN_FOUNDATION_DEPTH_M * 1.5:
            findings.append(Finding(
                "foundation_depth", "Foundation depth near a tree",
                ATTENTION, MAJOR,
                f"{tree.get('species', 'A tree')} at "
                f"{tree.get('distance_m')}m suggests a planning depth of "
                f"{depth['depth_m']}m ({depth['governed_by']}). "
                f"{depth['note']}",
                "NHBC Standards, Chapter 4.2",
                depth["depth_m"], "m"))

    if clay:
        findings.append(Finding(
            "clay_heave", "Shrinkable clay", ATTENTION, MAJOR,
            "On shrinkable clay, removing a mature tree can cause heave as "
            "the ground rehydrates over years — sometimes more damaging than "
            "the shrinkage it was causing. Where a tree is coming out, get "
            "advice before deciding foundation depth.",
            "NHBC Standards, Chapter 4.2"))
    return findings


def _compass(bearing):
    names = ["north", "north-east", "east", "south-east",
             "south", "south-west", "west", "north-west"]
    return names[int((bearing + 22.5) % 360 // 45)]


def assess(terrain_points=None, drainage_target_m=None, trees=None,
           clay=False, platform_level_m=None, cell_area_m2=1.0):
    """Full site assessment from terrain points."""
    info = levels(terrain_points) if terrain_points else None
    findings = check_site(info, drainage_target_m, trees, clay)

    earthworks = None
    if terrain_points:
        target = (platform_level_m if platform_level_m is not None
                  else balance_level(terrain_points))
        earthworks = cut_and_fill(terrain_points, target, cell_area_m2)

    by_sev = {CRITICAL: [], MAJOR: [], ADVISORY: []}
    for f in findings:
        if f.severity in by_sev:
            by_sev[f.severity].append(f.as_dict())

    return {
        "levels": info,
        "earthworks": earthworks,
        "findings": [f.as_dict() for f in findings],
        "critical": by_sev[CRITICAL],
        "major": by_sev[MAJOR],
        "advisory": by_sev[ADVISORY],
        "disclaimer":
            "Derived from a 1m terrain model. It cannot see soil type, "
            "bearing capacity, the water table, existing drains, buried "
            "services, made ground or contamination. Trial holes, a drainage "
            "survey and a service scan still decide what actually gets dug.",
    }
