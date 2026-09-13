"""Structure Mode — a metric point cloud becomes walls, slabs and rooms.

The broken link in the chain. reconstruct.py produces a scaled point cloud
and nothing consumes it: the X-ray needs walls to hang services on, condition
pins need surfaces to sit on, and designing an extension needs an as-built to
extend. All of it waits on turning a cloud of points into objects.

Approach follows Cloud2BIM (MIT, arXiv:2503.11498): density analysis and
morphological reasoning rather than RANSAC plane fitting. RANSAC is the
obvious choice and the wrong one indoors — it finds the largest plane, which
in a real room is the floor, then the ceiling, and it will happily fit a
plane through a sofa. Density works because buildings are made of parallel
surfaces at repeated heights, and that is a much stronger prior than
planarity.

Pure stdlib throughout, deliberately. The segmentation must run and be
testable on a bare interpreter; numpy is used only if it happens to be there,
and IFC authoring is behind a lazy import like every third-party dependency
in this worker.

WHAT THIS REFUSES TO DO. It will not emit structure from a cloud that is not
gravity-aligned, not metrically scaled, or too sparse to support the
conclusion. An IFC file is an authoritative-looking artefact — someone will
build from it — so a wrong one is worse than none.
"""
import math
import os
import struct

# --- limits, and why ------------------------------------------------------

# Voxel edge for downsampling, in metres. 25mm keeps door reveals and skirting
# distinguishable while making a multi-million-point cloud tractable in pure
# Python.
VOXEL_M = 0.025

# A storey slab shows as a sharp spike in the Z histogram. This is the bin
# width used to find it — fine enough to separate a floor from the skirting
# above it, coarse enough not to shatter a slab across bins.
Z_BIN_M = 0.05

# A horizontal band must hold at least this share of all points to be a slab.
# Floors and ceilings are the densest surfaces in any indoor scan by a wide
# margin, because they are what the scanner sees most of.
SLAB_SHARE = 0.04

# Storeys closer together than this are the same storey seen twice.
MIN_STOREY_SEPARATION_M = 1.8

# Plan-view cell for finding walls, in metres.
WALL_CELL_M = 0.05

# A plan cell needs this share of the storey's height to be wall rather than
# furniture. A wall runs floor to ceiling; a wardrobe does not.
WALL_VERTICAL_SHARE = 0.55

# Below this, a wall run is a doorframe or a stub, not a wall.
MIN_WALL_LENGTH_M = 0.4

# An open doorway leaves a gap in the traced wall (a scan only sees points
# above the door head). Gaps up to a generous door width between wall ends
# are bridged before the floor-area flood, or the fill leaks through and
# marks the whole room outside. 1.1m covers a 1076mm doorset.
DOORWAY_BRIDGE_M = 1.1

# If the flood-filled area is under this share of the wall extent, the trace
# did not close and the number is delivered with a warning, not bare.
ENVELOPE_COLLAPSE_SHARE = 0.3

# Used only when a scan saw one face of a wall and its thickness is therefore
# not observable. A UK internal stud partition is 100mm over the studs.
DEFAULT_WALL_THICKNESS_M = 0.1

# No merged run wider than this is a wall — it is the perpendicular wall seen
# end-on. Solid stone can reach 600mm; beyond that it is a merge artefact.
MAX_WALL_THICKNESS_M = 0.6

# Nominal slab depth for the IFC floor. Not measured — a scan sees the top of
# the floor and nothing below it.
SLAB_THICKNESS_M = 0.15

# UK domestic sanity band. Anything outside it means the scale is wrong, and
# the scale being wrong is the failure that quietly poisons everything.
MIN_STOREY_HEIGHT_M = 1.9
MAX_STOREY_HEIGHT_M = 4.5

# A cloud this sparse cannot support conclusions about structure.
MIN_POINTS = 5000

# Widest a single building may span before this is a street rather than a
# property. Generous — it clears any UK domestic building and most commercial
# ones — but a scan that covers 200m has picked up the neighbours, and roof
# mode already learned that lesson the expensive way: without a footprint it
# once returned 2,696 m2 of roof for an entire street.
MAX_SPAN_M = 200.0


class StructureError(ValueError):
    """Raised when structure cannot be derived honestly.

    Deliberately fatal. An IFC file looks authoritative and someone will
    build from it, so producing a wrong one is worse than producing none.
    """


# --- reading a cloud -------------------------------------------------------

def read_ply(path, max_points=2_000_000):
    """Read a PLY point cloud. Pure stdlib, ASCII and binary little-endian.

    Written rather than pulled in because the alternatives are heavy: Open3D
    is 1,066 MB and needs libGL on a slim image, for a job that is parsing a
    header and unpacking floats.
    """
    if not path or not os.path.exists(path):
        raise StructureError(f"point cloud not found: {path}")

    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise StructureError(f"{path} is not a PLY file")

        fmt, count, properties, in_vertex = None, 0, [], False
        while True:
            line = f.readline()
            if not line:
                raise StructureError("PLY header ended without end_header")
            parts = line.split()
            if not parts:
                continue
            keyword = parts[0]
            if keyword == b"format":
                fmt = parts[1].decode()
            elif keyword == b"element":
                in_vertex = parts[1] == b"vertex"
                if in_vertex:
                    count = int(parts[2])
            elif keyword == b"property" and in_vertex:
                properties.append((parts[1].decode(), parts[2].decode()))
            elif keyword == b"end_header":
                break

        if fmt is None:
            raise StructureError("PLY header declares no format")
        if count <= 0:
            raise StructureError("PLY declares no vertices")

        names = [n for _t, n in properties]
        for axis in ("x", "y", "z"):
            if axis not in names:
                raise StructureError(
                    f"PLY vertices have no {axis} coordinate — this is not a "
                    f"point cloud this worker can read")
        ix, iy, iz = names.index("x"), names.index("y"), names.index("z")

        if fmt == "ascii":
            return _read_ply_ascii(f, count, ix, iy, iz, max_points)
        if fmt.startswith("binary_little_endian"):
            return _read_ply_binary(f, count, properties, ix, iy, iz,
                                    max_points)
        raise StructureError(f"unsupported PLY format {fmt!r}")


def _read_ply_ascii(f, count, ix, iy, iz, max_points):
    step = max(1, count // max_points)
    points = []
    for i in range(count):
        line = f.readline()
        if not line:
            break
        if i % step:
            continue
        parts = line.split()
        try:
            points.append((float(parts[ix]), float(parts[iy]),
                           float(parts[iz])))
        except (IndexError, ValueError):
            continue
    return points


_PLY_TYPES = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}


def _read_ply_binary(f, count, properties, ix, iy, iz, max_points):
    try:
        fmt = "<" + "".join(_PLY_TYPES[t] for t, _n in properties)
    except KeyError as e:
        raise StructureError(f"unsupported PLY property type {e}")
    size = struct.calcsize(fmt)
    data = f.read(size * count)
    step = max(1, count // max_points)

    points = []
    for i in range(0, count, step):
        offset = i * size
        chunk = data[offset:offset + size]
        if len(chunk) < size:
            break
        values = struct.unpack(fmt, chunk)
        points.append((values[ix], values[iy], values[iz]))
    return points


# --- preparation -----------------------------------------------------------

def voxel_downsample(points, voxel_m=VOXEL_M):
    """One point per occupied voxel.

    Density analysis needs occupancy, not sample count. Without this a wall
    the scanner happened to dwell on outweighs one it passed quickly, and the
    histogram describes the operator's walking speed rather than the building.
    """
    if voxel_m <= 0:
        raise StructureError("voxel size must be positive")
    seen = {}
    for x, y, z in points:
        key = (int(math.floor(x / voxel_m)), int(math.floor(y / voxel_m)),
               int(math.floor(z / voxel_m)))
        if key not in seen:
            seen[key] = (x, y, z)
    return list(seen.values())


def bounds(points):
    """Axis-aligned extent as (min_x, min_y, min_z, max_x, max_y, max_z)."""
    if not points:
        raise StructureError("no points")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def check_metric(points):
    """Refuse a cloud whose dimensions are not plausibly a building in metres.

    The failure this catches is the one that poisons everything downstream: a
    cloud in centimetres or in arbitrary units segments perfectly happily and
    produces a house 30cm tall or 300m tall, with every wall and slab in the
    right place relative to each other. Nothing looks wrong except the units.
    """
    box = bounds(points)
    height = box[5] - box[2]
    width = max(box[3] - box[0], box[4] - box[1])

    if height < 1.5:
        raise StructureError(
            f"this cloud is {height:.2f}m tall, which is not a building. The "
            f"scale is almost certainly wrong — a model in centimetres reads "
            f"exactly like this. Fix the scale before deriving structure.")
    if height > 200:
        raise StructureError(
            f"this cloud is {height:.0f}m tall. Either the scale is wrong or "
            f"this is not a single building.")
    if width > MAX_SPAN_M:
        raise StructureError(
            f"this cloud spans {width:.0f}m. That is a street, not a "
            f"building — clip to the property first.")
    return {"height_m": round(height, 3), "width_m": round(width, 3)}


def check_gravity_aligned(points, sample=20000):
    """Refuse a cloud that is not Z-up.

    Everything below assumes floors are horizontal and walls vertical. A
    tilted cloud does not fail loudly — it produces sloping "slabs" and walls
    that taper, which reads as a badly built house rather than a badly
    aligned scan.

    Detected by looking for the strong horizontal bands a building always
    has. If the Z histogram is flat, the cloud is not standing up.
    """
    if len(points) < MIN_POINTS:
        raise StructureError(
            f"only {len(points)} points — too sparse to derive structure "
            f"from. At least {MIN_POINTS} are needed to tell a wall from "
            f"noise.")

    # Strided, not the first N. A PLY is written in whatever order the
    # producer chose — commonly floor block first, then walls — so a prefix
    # of a perfectly good room can be one flat slab, and the check refused
    # it as "not gravity-aligned". A stride crosses the whole file.
    step = max(1, len(points) // sample)
    zs = [points[i][2] for i in range(0, len(points), step)]
    lo, hi = min(zs), max(zs)
    if hi - lo <= 0:
        raise StructureError("this cloud is flat — it has no height at all")

    bins = {}
    for z in zs:
        bins[int((z - lo) / Z_BIN_M)] = bins.get(int((z - lo) / Z_BIN_M), 0) + 1

    peak = max(bins.values()) / len(zs)
    if peak < SLAB_SHARE:
        raise StructureError(
            f"no horizontal surface stands out in this cloud (densest height "
            f"band holds {peak * 100:.1f}% of points). Either it is not "
            f"gravity-aligned — floors must be level and Z must be up — or it "
            f"is too noisy to segment. Align it before deriving structure.")
    return {"strongest_band_share": round(peak, 4)}


# --- slabs and storeys -----------------------------------------------------

def z_histogram(points, bin_m=Z_BIN_M):
    """Occupancy by height. The basis for everything that follows."""
    box = bounds(points)
    base = box[2]
    hist = {}
    for _x, _y, z in points:
        index = int((z - base) / bin_m)
        hist[index] = hist.get(index, 0) + 1
    return base, hist


def find_slabs(points, bin_m=Z_BIN_M, share=SLAB_SHARE):
    """Horizontal surfaces, as heights in metres.

    A floor or ceiling is a spike in the height histogram: thousands of
    points within a few centimetres. Furniture is broad and low; a slab is
    narrow and tall.

    Adjacent bins are merged, because a real floor is never perfectly level
    and a 50mm bin will split it.
    """
    if not points:
        raise StructureError("no points to find slabs in")
    base, hist = z_histogram(points, bin_m)
    total = len(points)
    threshold = total * share

    peaks = sorted(i for i, n in hist.items() if n >= threshold)
    if not peaks:
        return []

    groups, current = [], [peaks[0]]
    for index in peaks[1:]:
        if index - current[-1] <= 1:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    groups.append(current)

    slabs = []
    for group in groups:
        weight = sum(hist[i] for i in group)
        centre = sum(hist[i] * (base + (i + 0.5) * bin_m) for i in group)
        slabs.append({
            "z_m": round(centre / weight, 3),
            "points": weight,
            "share": round(weight / total, 4),
        })
    return sorted(slabs, key=lambda s: s["z_m"])


def storeys_from_slabs(slabs, min_separation=MIN_STOREY_SEPARATION_M):
    """Pair slabs into storeys — a floor and the ceiling above it.

    Refuses heights outside the UK domestic band rather than reporting a
    2.4m-high building as having one very short storey, because that is what
    a scale error looks like.
    """
    if len(slabs) < 2:
        raise StructureError(
            f"found {len(slabs)} horizontal surface(s). A storey needs a "
            f"floor and a ceiling; this scan probably covers only part of a "
            f"room, or the cloud is too noisy for the floor to stand out.")

    storeys, floor = [], slabs[0]
    for ceiling in slabs[1:]:
        height = ceiling["z_m"] - floor["z_m"]
        if height < min_separation:
            # Too close to be a storey — a raised threshold, a mezzanine
            # edge, or the same slab found twice. Keep the denser one.
            if ceiling["points"] > floor["points"]:
                floor = ceiling
            continue
        storeys.append({
            "floor_z_m": floor["z_m"],
            "ceiling_z_m": ceiling["z_m"],
            "height_m": round(height, 3),
            "plausible": MIN_STOREY_HEIGHT_M <= height <= MAX_STOREY_HEIGHT_M,
        })
        floor = ceiling

    if not storeys:
        raise StructureError(
            "no floor-and-ceiling pair could be found far enough apart to be "
            "a storey. Check the cloud covers a whole room, floor to ceiling.")
    return storeys


# --- walls -----------------------------------------------------------------

def wall_cells(points, storey, cell_m=WALL_CELL_M,
               vertical_share=WALL_VERTICAL_SHARE):
    """Plan cells that are wall rather than contents.

    The discriminator is vertical extent, not density. A wall occupies its
    plan cell from floor to ceiling; a worktop, a radiator and a sofa do not.
    Measuring how much of the storey's height each cell spans separates them
    without any furniture model and without training data.

    HOW FAR THAT ACTUALLY GOES, measured rather than asserted: at 0.55 of a
    2.1m working span the cut lands at about 1.30m. A 0.9m worktop is
    correctly rejected. A 2.0m wardrobe is not — it reads as wall, and a
    room with one came back with 8 walls instead of 4 and 21% more wall
    length. Full-height wardrobes, fridge-freezers, bookcases and shower
    enclosures all clear the bar. The claim this docstring used to make —
    that it "removes furniture" — was true of low furniture only, and the
    fixture that verified it used a 0.8m block labelled "wardrobe".

    So segment() now warns when tall free-standing objects are the likely
    reading, rather than presenting the count as clean.
    """
    floor_z = storey["floor_z_m"]
    ceiling_z = storey["ceiling_z_m"]
    height = ceiling_z - floor_z
    if height <= 0:
        raise StructureError("storey has no height")

    # Ignore the slabs themselves, or every cell reads as full-height.
    margin = min(0.15, height * 0.1)
    low, high = floor_z + margin, ceiling_z - margin
    span = high - low
    if span <= 0:
        raise StructureError("storey is too shallow to look for walls in")

    cells = {}
    for x, y, z in points:
        if not low <= z <= high:
            continue
        key = (int(math.floor(x / cell_m)), int(math.floor(y / cell_m)))
        seen = cells.get(key)
        if seen is None:
            cells[key] = [z, z, x, x, y, y, x, y, 1]
        else:
            if z < seen[0]:
                seen[0] = z
            if z > seen[1]:
                seen[1] = z
            if x < seen[2]:
                seen[2] = x
            if x > seen[3]:
                seen[3] = x
            if y < seen[4]:
                seen[4] = y
            if y > seen[5]:
                seen[5] = y
            seen[6] += x
            seen[7] += y
            seen[8] += 1

    out = {}
    for key, (z0, z1, x0, x1, y0, y1, sx, sy, n) in cells.items():
        share = (z1 - z0) / span
        if share >= vertical_share:
            # The real coordinates, kept alongside the share. Reporting the
            # cell CENTRE instead put a systematic +25mm bias on every wall
            # plane, which matters because services.py drills against it.
            out[key] = {"share": share, "x_min": x0, "x_max": x1,
                        "y_min": y0, "y_max": y1,
                        "x_mean": sx / n, "y_mean": sy / n}
    return out


def trace_walls(cells, cell_m=WALL_CELL_M, min_length=MIN_WALL_LENGTH_M):
    """Group wall cells into straight runs, one per wall.

    Axis-aligned runs only, and that is a stated limitation rather than an
    oversight: a bay window or a splayed return will come back as a staircase
    of short segments. Handling arbitrary angles well needs the full
    morphological treatment, and reporting honest fragments beats inventing a
    smooth wall that is not there.

    PARALLEL ROWS ARE MERGED, and the first version did not do this. A wall
    is thick: 215mm of masonry fills four or five 50mm cells across, and each
    row was traced as its own full-length wall. A four-wall room came back
    with twenty walls and 5.3x the true centreline length, straight into
    totals.wall_length_m and the material order. It survived every test
    because the test fixture builds zero-thickness single-plane walls — the
    one case that cannot trigger it — while its comment claims 0.1m.

    Merging also recovers the thickness, which is worth having on its own:
    services.py needs it, and a scan that saw both faces of a wall has
    measured something no drawing take-off can.
    """
    if not cells:
        return []

    groups = []
    for axis in (0, 1):
        lines = {}
        for (cx, cy) in cells:
            key = cy if axis == 0 else cx
            lines.setdefault(key, []).append(cx if axis == 0 else cy)

        segments = []
        for key, along in lines.items():
            along.sort()
            start = previous = along[0]
            for value in along[1:] + [None]:
                if value is not None and value - previous <= 1:
                    previous = value
                    continue
                segments.append((key, start, previous))
                if value is None:
                    break
                start = previous = value
        groups.extend(_merge_parallel(axis, segments, cells, min_length))

    return sorted(groups, key=lambda r: -r["length_m"])


def _merge_parallel(axis, segments, cells, min_length):
    """Collapse the rows through one wall into a single centreline run."""
    # Chain segments on nearby lines that describe the SAME wall.
    #
    # Two conditions, and the second one is not optional. Adjacency alone
    # merged the single-cell stubs that a perpendicular wall leaves on every
    # line it crosses: each stub touched the long run at one end, chained to
    # the next stub, and the whole room collapsed into one cluster 4m
    # "thick", which the thickness filter then discarded — a four-wall room
    # traced as zero walls. Requiring the extents to substantially COINCIDE
    # keeps the rows of one wall together and leaves the crossing stubs to
    # the other axis, which traces them properly.
    #
    # The window is the widest wall worth believing rather than one cell,
    # because a scan usually sees a wall's two FACES with a hollow gap
    # between them — 215mm of masonry is five empty rows, not five full ones.
    window = max(1, int(round(MAX_WALL_THICKNESS_M / WALL_CELL_M)))
    segments.sort(key=lambda s: (s[0], s[1]))
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (ki, lo_i, hi_i) in enumerate(segments):
        span_i = hi_i - lo_i + 1
        for j in range(i + 1, len(segments)):
            kj, lo_j, hi_j = segments[j]
            if kj - ki > window:
                break
            if kj == ki:
                continue
            overlap = min(hi_i, hi_j) - max(lo_i, lo_j) + 1
            if overlap >= 0.8 * max(span_i, hi_j - lo_j + 1):
                parent[find(j)] = find(i)

    clusters = {}
    for i in range(len(segments)):
        clusters.setdefault(find(i), []).append(segments[i])

    runs = []
    for members in clusters.values():
        along_lo = min(m[1] for m in members)
        along_hi = max(m[2] for m in members)
        # Real coordinates, not cell indices: the cell centre carried a
        # systematic +25mm bias.
        perp_lo, perp_hi, along_min, along_max = None, None, None, None
        perp_sum, count = 0.0, 0
        for key, lo, hi in members:
            for index in range(lo, hi + 1):
                cell = cells.get((index, key) if axis == 0 else (key, index))
                if cell is None:
                    continue
                if axis == 0:
                    p_lo, p_hi = cell["y_min"], cell["y_max"]
                    a_lo, a_hi, p_mean = cell["x_min"], cell["x_max"], cell["y_mean"]
                else:
                    p_lo, p_hi = cell["x_min"], cell["x_max"]
                    a_lo, a_hi, p_mean = cell["y_min"], cell["y_max"], cell["x_mean"]
                perp_lo = p_lo if perp_lo is None else min(perp_lo, p_lo)
                perp_hi = p_hi if perp_hi is None else max(perp_hi, p_hi)
                along_min = a_lo if along_min is None else min(along_min, a_lo)
                along_max = a_hi if along_max is None else max(along_max, a_hi)
                perp_sum += p_mean
                count += 1
        if not count:
            continue

        length = along_max - along_min
        thickness = perp_hi - perp_lo
        if length < min_length:
            continue
        # A run wider than it is long is the perpendicular wall seen end-on;
        # the other axis traces it properly.
        if thickness > min(MAX_WALL_THICKNESS_M, length):
            continue

        centre = perp_sum / count
        a = (along_min, centre) if axis == 0 else (centre, along_min)
        b = (along_max, centre) if axis == 0 else (centre, along_max)
        runs.append({
            "start": (round(a[0], 3), round(a[1], 3)),
            "end": (round(b[0], 3), round(b[1], 3)),
            "length_m": round(length, 3),
            "thickness_m": round(thickness, 3),
            "axis": "x" if axis == 0 else "y",
        })
    return runs


# --- the whole thing -------------------------------------------------------

def segment(points, voxel_m=VOXEL_M):
    """Point cloud in, structure out. Every guard applied first."""
    if not points:
        raise StructureError("no points supplied")

    checks = {"points_in": len(points)}
    reduced = voxel_downsample(points, voxel_m)
    checks["points_after_voxel"] = len(reduced)

    checks.update(check_metric(reduced))
    checks.update(check_gravity_aligned(reduced))

    slabs = find_slabs(reduced)
    storeys = storeys_from_slabs(slabs)

    for storey in storeys:
        cells = wall_cells(reduced, storey)
        storey["wall_cells"] = len(cells)
        storey["walls"] = trace_walls(cells)
        for wall in storey["walls"]:
            _attach_frame(wall, storey)
        storey["wall_length_m"] = round(
            sum(w["length_m"] for w in storey["walls"]), 2)
        # Floor area from the wall envelope, not the point extent: the extent
        # includes anything the scanner saw through a doorway.
        area, area_note = _envelope_area(storey["walls"])
        storey["floor_area_m2"] = area
        if area_note:
            storey["floor_area_note"] = area_note

    warnings = []
    for i, storey in enumerate(storeys):
        if storey.get("floor_area_note"):
            warnings.append(f"Storey {i + 1}: {storey['floor_area_note']}")
        if not storey["plausible"]:
            warnings.append(
                f"Storey {i + 1} is {storey['height_m']:.2f}m floor to "
                f"ceiling, outside the {MIN_STOREY_HEIGHT_M}–"
                f"{MAX_STOREY_HEIGHT_M}m range of UK domestic construction. "
                f"Check the scale before trusting any quantity from it.")
        if not storey["walls"]:
            warnings.append(
                f"Storey {i + 1} has no walls long enough to trace. The scan "
                f"may not reach the room edges.")
    warnings.append(
        "Walls are traced axis-aligned, so bays, splays and curved returns "
        "come back as short segments rather than one run.")
    warnings.append(
        f"Anything standing more than about "
        f"{WALL_VERTICAL_SHARE * 2.1:.1f}m floor to ceiling reads as wall. "
        f"A worktop or a radiator is correctly ignored, but a full-height "
        f"wardrobe, fridge-freezer, bookcase or shower enclosure is not — "
        f"check the plan against the room before ordering from it.")

    return {
        "checks": checks,
        "slabs": slabs,
        "storeys": storeys,
        "totals": {
            "storeys": len(storeys),
            "walls": sum(len(s["walls"]) for s in storeys),
            "wall_length_m": round(
                sum(s["wall_length_m"] for s in storeys), 2),
            "floor_area_m2": round(
                sum(s["floor_area_m2"] for s in storeys), 2),
        },
        "method": ("density and vertical-extent segmentation, after "
                   "Cloud2BIM (MIT) — not RANSAC, which indoors fits the "
                   "floor and then the furniture"),
        "warnings": warnings,
    }


def _attach_frame(wall, storey):
    """Give a wall the frame services mode needs to hang a run on.

    services.py refused a wall without one and said "structure mode produces
    it". Structure mode did not: it emitted start, end, length_m and axis,
    and nothing else. The documented handoff between the two modules — the
    X-ray, the thing the whole product is for — did not connect, and the
    error message telling the caller so was itself the false claim.

    origin is the wall's bottom-left corner in world space: the start of the
    centreline at floor level. Without it, services' (u, v) coordinates are
    raw world projections that mean nothing to whoever has to find the pipe.
    """
    (x0, y0), (x1, y1) = wall["start"], wall["end"]
    length = wall["length_m"]
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    # Plane through the centreline, normal horizontal and perpendicular to it.
    nx, ny = -uy, ux
    base_z = storey["floor_z_m"]

    wall["origin"] = (round(x0, 3), round(y0, 3), round(base_z, 3))
    wall["direction"] = (round(ux, 6), round(uy, 6), 0.0)
    wall["width_m"] = length
    wall["height_m"] = storey["height_m"]
    wall["plane"] = (round(nx, 6), round(ny, 6), 0.0,
                     round(-(nx * x0 + ny * y0), 6))


def _envelope_area(walls):
    """Plan area actually enclosed by the traced walls.

    This was a bounding box, presented by the comment above its call site as
    a considered choice — "from the wall envelope, not the point extent". A
    bounding box is not an envelope. On an L-shaped room whose six walls were
    all traced correctly it reported 42.65 m2 against a true 33.0, +29%, and
    every UK house with a rear extension is an L.

    Occupancy of the plan grid, not a polygon fit: the walls are axis-aligned
    segments with no ordering and no guarantee of closure, so there is no
    ring to run a shoelace over. Filling the cells the walls bound and
    counting them handles L, T, U and stepped plans without pretending the
    tracer produced something it did not.

    DOORWAYS ARE GAPS. A real scan of a room with an open doorway leaves a
    break in the traced wall (points only above the door head), and a flood
    from the border pours through it, marking the whole room outside — a
    5x4m room came back as 0.43 m2, silently. Gaps up to a door's width
    between wall ends are bridged before flooding; the bridge is a barrier
    only, its cells are doorway floor. If the fill still collapses against
    the wall extent, the number is returned WITH a warning note instead of
    alone, because a wildly wrong area delivered with confidence is the
    exact thing this project refuses to do.

    Returns (area_m2, note) — note is None when the fill is trustworthy.
    """
    if not walls:
        return 0.0, None

    cell = WALL_CELL_M
    xs = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
    ys = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return 0.0, None

    nx = int(math.ceil((x1 - x0) / cell)) + 1
    ny = int(math.ceil((y1 - y0) / cell)) + 1
    if nx * ny > 4_000_000:          # a 100m x 100m plan at 50mm; beyond that
        return round((x1 - x0) * (y1 - y0), 2), \
            "plan too large for the fill grid — area is the wall extent"

    wall = [[False] * ny for _ in range(nx)]

    def _stamp(grid, ax, ay, bx, by):
        steps = int(math.ceil(max(abs(bx - ax), abs(by - ay)) / cell)) + 1
        for s in range(steps + 1):
            t = s / steps
            i = int(round((ax + (bx - ax) * t - x0) / cell))
            j = int(round((ay + (by - ay) * t - y0) / cell))
            if 0 <= i < nx and 0 <= j < ny:
                grid[i][j] = True

    for w in walls:
        (ax, ay), (bx, by) = w["start"], w["end"]
        _stamp(wall, ax, ay, bx, by)

    # Bridge door-sized gaps between wall ends so the flood cannot leak
    # through an open doorway. Bridges block the flood but are NOT wall:
    # the floor runs through a doorway.
    bridge = [[False] * ny for _ in range(nx)]
    ends = [w["start"] for w in walls] + [w["end"] for w in walls]
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            gap = math.dist(ends[a], ends[b])
            if cell < gap <= DOORWAY_BRIDGE_M:
                _stamp(bridge, ends[a][0], ends[a][1],
                       ends[b][0], ends[b][1])

    # Flood from the border. What the flood cannot reach is inside.
    outside = [[False] * ny for _ in range(nx)]
    stack = []

    def _barrier(i, j):
        return wall[i][j] or bridge[i][j]

    for i in range(nx):
        for j in (0, ny - 1):
            if not _barrier(i, j) and not outside[i][j]:
                outside[i][j] = True
                stack.append((i, j))
    for j in range(ny):
        for i in (0, nx - 1):
            if not _barrier(i, j) and not outside[i][j]:
                outside[i][j] = True
                stack.append((i, j))
    while stack:
        i, j = stack.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < nx and 0 <= b < ny and not _barrier(a, b) \
                    and not outside[a][b]:
                outside[a][b] = True
                stack.append((a, b))

    inside = sum(1 for i in range(nx) for j in range(ny)
                 if not outside[i][j] and not wall[i][j])
    # Wall cells are half floor, half wall; counting them whole overstates a
    # small room and dropping them understates every room.
    on_wall = sum(1 for i in range(nx) for j in range(ny) if wall[i][j])
    area = round((inside + on_wall * 0.5) * cell * cell, 2)

    # The refusal-to-mislead check: if what the walls bound is a sliver of
    # the extent they span, the trace did not close and the fill leaked.
    extent = (x1 - x0) * (y1 - y0)
    if extent > 1.0 and area < ENVELOPE_COLLAPSE_SHARE * extent:
        return area, (
            f"the traced walls do not enclose the plan: the fill bounds "
            f"{area:.2f} m2 inside a {extent:.1f} m2 wall extent, so the "
            f"trace has openings wider than a door and the area is NOT "
            f"trustworthy — do not order from it")
    return area, None


# --- IFC -------------------------------------------------------------------

def write_ifc(structure, path, project_name="Scanned Building"):
    """Author an IFC4 file from the segmentation. Lazy import, by design.

    THIS FUNCTION HAD NEVER ONCE RUN. It carried a confident docstring about
    two traps "found by running this rather than reading about it", and both
    were transcribed from notes; the code underneath used `ip_class=` for
    `ifc_class=` in five places and reached for `ifcopenshell.api.project`
    without importing the submodule. Every structure job on the deployed
    image died with an AttributeError. CI never saw it because CI installs
    nothing, so the ImportError branch fired and the test — which asserted
    only `res["ifc"] in (True, False)` — passed on a bare interpreter.

    The units trap below IS real and is verified by test_structure: an
    IFC written in millimetres scales the building by 1000 and every
    quantity with it.

    What this emits: IfcProject / IfcSite / IfcBuilding / IfcBuildingStorey,
    with an IfcSlab per storey floor and an IfcWall per traced wall, each
    with a real placement and a swept-solid body. NOT openings and NOT
    spaces — nothing in the segmentation detects a door, a window or a room
    boundary, so there is nothing honest to write for them.
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
    except ImportError:
        raise StructureError(
            "ifcopenshell is not installed in this worker, so IFC cannot be "
            "written. The segmentation above is still valid — install "
            "ifcopenshell (LGPL) to export it.")

    run = ifcopenshell.api.run
    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = run("root.create_entity", model, ifc_class="IfcProject",
                  name=project_name)

    # METRES, explicitly. See the docstring — the default is millimetres.
    metre = ifcopenshell.api.unit.add_si_unit(
        model, unit_type="LENGTHUNIT", prefix=None)
    ifcopenshell.api.unit.assign_unit(model, units=[metre])

    context = run("context.add_context", model, context_type="Model")
    body = run("context.add_context", model, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW",
               parent=context)

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", model, ifc_class="IfcBuilding",
                   name=project_name)
    run("aggregate.assign_object", model, products=[site],
        relating_object=project)
    run("aggregate.assign_object", model, products=[building],
        relating_object=site)

    for index, storey in enumerate(structure["storeys"]):
        level = run("root.create_entity", model,
                    ifc_class="IfcBuildingStorey", name=f"Level {index}")
        run("aggregate.assign_object", model, products=[level],
            relating_object=building)
        base_z = storey["floor_z_m"]
        height = storey["height_m"]

        for wall in storey["walls"]:
            element = run("root.create_entity", model, ifc_class="IfcWall",
                          name=f"Wall {wall['axis']} {wall['length_m']}m")
            run("spatial.assign_container", model, products=[element],
                relating_structure=level)
            _place_wall(model, run, body, element, wall, base_z, height)

        slab = _slab_outline(storey["walls"])
        if slab:
            element = run("root.create_entity", model, ifc_class="IfcSlab",
                          predefined_type="FLOOR", name=f"Floor {index}")
            run("spatial.assign_container", model, products=[element],
                relating_structure=level)
            _place_slab(model, run, body, element, slab, base_z)

    model.write(path)
    return path


def _place_wall(model, run, body, element, wall, base_z, height):
    """Give a wall an origin and an extruded body, in metres.

    A wall with no ObjectPlacement and no Representation is a name in a file.
    Every viewer opens it, shows nothing, and the file looks authoritative
    while carrying no building at all.
    """
    (x0, y0), (x1, y1) = wall["start"], wall["end"]
    thickness = wall.get("thickness_m") or DEFAULT_WALL_THICKNESS_M
    length = wall["length_m"]
    dx, dy = (x1 - x0), (y1 - y0)
    if length <= 0:
        return
    ux, uy = dx / length, dy / length

    run("geometry.edit_object_placement", model, product=element,
        matrix=(
            (ux, -uy, 0.0, x0),
            (uy, ux, 0.0, y0),
            (0.0, 0.0, 1.0, base_z),
            (0.0, 0.0, 0.0, 1.0),
        ))
    profile = model.create_entity(
        "IfcRectangleProfileDef", ProfileType="AREA",
        XDim=float(length), YDim=float(thickness),
        Position=model.create_entity(
            "IfcAxis2Placement2D",
            Location=model.create_entity(
                "IfcCartesianPoint", Coordinates=(length / 2.0, 0.0))))
    _extrude(model, run, body, element, profile, height)


def _place_slab(model, run, body, element, outline, base_z):
    """A storey floor as a thin extrusion of the traced outline."""
    points = [model.create_entity("IfcCartesianPoint",
                                  Coordinates=(float(x), float(y)))
              for x, y in outline]
    polyline = model.create_entity("IfcPolyline", Points=points + [points[0]])
    profile = model.create_entity(
        "IfcArbitraryClosedProfileDef", ProfileType="AREA",
        OuterCurve=polyline)
    run("geometry.edit_object_placement", model, product=element,
        matrix=(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, base_z - SLAB_THICKNESS_M),
            (0.0, 0.0, 0.0, 1.0),
        ))
    _extrude(model, run, body, element, profile, SLAB_THICKNESS_M)


def _extrude(model, run, body, element, profile, depth):
    solid = model.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile,
        Position=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0))),
        ExtrudedDirection=model.create_entity("IfcDirection",
                                              DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=float(depth))
    shape = model.create_entity(
        "IfcShapeRepresentation", ContextOfItems=body,
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        Items=[solid])
    run("geometry.assign_representation", model, product=element,
        representation=shape)


def _slab_outline(walls):
    """A closed floor outline from the traced walls, or None.

    The rectangular hull of the wall centrelines. Honest for the rectangular
    and near-rectangular rooms this tracer handles well, and deliberately
    absent when there are too few walls to imply an enclosure at all.
    """
    if len(walls) < 3:
        return None
    xs = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
    ys = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- handler entry point ---------------------------------------------------

def run_mode(spec, prog, output_dir):
    """Structure mode entry point."""
    import json
    import paths

    prog.stage("fetching")
    cloud = spec.get("point_cloud_path") or spec.get("point_cloud_url")
    if not cloud:
        raise StructureError(
            "structure mode needs a point cloud: point_cloud_url from a "
            "reconstruct job, or point_cloud_path for a local file.")

    if not os.path.exists(cloud):
        import validation
        directory = paths.ensure(output_dir)
        local = os.path.join(directory, "cloud.ply")
        response = validation.fetch_checked(cloud, "point_cloud_url",
                                            timeout=600)
        response.raise_for_status()
        with open(local, "wb") as f:
            f.write(response.content)
        cloud = local

    points = read_ply(cloud, max_points=spec.get("max_points") or 2_000_000)

    prog.stage("segmenting")
    result = segment(points, voxel_m=spec.get("voxel_m") or VOXEL_M)

    prog.stage("building_ifc")
    directory = paths.ensure(output_dir)
    scan = spec.get("scan_id") or "structure"
    artifacts = []
    ifc_path = os.path.join(directory, f"{scan}.ifc")
    try:
        write_ifc(result, ifc_path, project_name=scan)
        artifacts.append((ifc_path, f"structure/{scan}.ifc", None))
        result["ifc"] = True
    except Exception as e:
        # Deliberately broad. A StructureError-only catch let an
        # AttributeError out of the IFC writer, and the handler's generic
        # handler then threw away a segmentation that had already succeeded
        # — the exact outcome the code below exists to prevent. The
        # segmentation is the valuable part; the IFC is an export of it.
        result["ifc"] = False
        result["warnings"].append(
            f"IFC export failed ({type(e).__name__}: {e}). The segmentation "
            f"below is unaffected.")

    prog.stage("exporting")
    json_path = os.path.join(directory, f"{scan}.structure.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    artifacts.append((json_path, f"structure/{scan}.json", None))

    return artifacts, {"structure": result, "warnings": result["warnings"]}


run = run_mode
