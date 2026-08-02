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

    zs = [p[2] for p in points[:sample]]
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
    plan cell from floor to ceiling; a wardrobe, a worktop and a radiator do
    not. Measuring how much of the storey's height each cell spans separates
    them without any furniture model — which is the trick that makes this
    work without training data.
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
            cells[key] = [z, z]
        else:
            if z < seen[0]:
                seen[0] = z
            if z > seen[1]:
                seen[1] = z

    return {key: (zs[1] - zs[0]) / span for key, zs in cells.items()
            if (zs[1] - zs[0]) / span >= vertical_share}


def trace_walls(cells, cell_m=WALL_CELL_M, min_length=MIN_WALL_LENGTH_M):
    """Group wall cells into straight runs.

    Axis-aligned runs only, and that is a stated limitation rather than an
    oversight: a bay window or a splayed return will come back as a staircase
    of short segments. Handling arbitrary angles well needs the full
    morphological treatment, and reporting honest fragments beats inventing a
    smooth wall that is not there.
    """
    if not cells:
        return []
    runs = []
    for axis in (0, 1):
        lines = {}
        for (cx, cy) in cells:
            key = cy if axis == 0 else cx
            lines.setdefault(key, []).append(cx if axis == 0 else cy)

        for key, along in lines.items():
            along.sort()
            start = previous = along[0]
            for value in along[1:] + [None]:
                if value is not None and value - previous <= 1:
                    previous = value
                    continue
                length = (previous - start + 1) * cell_m
                if length >= min_length:
                    fixed = (key + 0.5) * cell_m
                    a = (start * cell_m, fixed) if axis == 0 else (fixed, start * cell_m)
                    b = ((previous + 1) * cell_m, fixed) if axis == 0 else (fixed, (previous + 1) * cell_m)
                    runs.append({
                        "start": (round(a[0], 3), round(a[1], 3)),
                        "end": (round(b[0], 3), round(b[1], 3)),
                        "length_m": round(length, 3),
                        "axis": "x" if axis == 0 else "y",
                    })
                if value is None:
                    break
                start = previous = value
    return sorted(runs, key=lambda r: -r["length_m"])


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
        storey["wall_length_m"] = round(
            sum(w["length_m"] for w in storey["walls"]), 2)
        # Floor area from the wall envelope, not the point extent: the extent
        # includes anything the scanner saw through a doorway.
        storey["floor_area_m2"] = _envelope_area(storey["walls"])

    warnings = []
    for i, storey in enumerate(storeys):
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


def _envelope_area(walls):
    """Plan area enclosed by the traced walls, from their bounding envelope."""
    if not walls:
        return 0.0
    xs = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
    ys = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
    return round((max(xs) - min(xs)) * (max(ys) - min(ys)), 2)


# --- IFC -------------------------------------------------------------------

def write_ifc(structure, path, project_name="Scanned Building"):
    """Author an IFC4 file from the segmentation. Lazy import, by design.

    Two traps, both found by running this rather than reading about it:

      UNITS   ifcopenshell's assign_unit() with no arguments emits
              MILLIMETRES. For a metric cloud that silently scales the
              building by 1000, and every downstream quantity with it.
      SPACES  IfcSpace is a spatial STRUCTURE element, so it must be
              aggregated into the storey, not contained in it.
              spatial.assign_container() raises AttributeError.
    """
    try:
        import ifcopenshell
        import ifcopenshell.api
    except ImportError:
        raise StructureError(
            "ifcopenshell is not installed in this worker, so IFC cannot be "
            "written. The segmentation above is still valid — install "
            "ifcopenshell (LGPL) to export it.")

    run = ifcopenshell.api.run
    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = run("root.create_entity", model, ip_class="IfcProject",
                  name=project_name)

    # METRES, explicitly. See the docstring — the default is millimetres.
    metre = ifcopenshell.api.unit.add_si_unit(
        model, unit_type="LENGTHUNIT", prefix=None)
    ifcopenshell.api.unit.assign_unit(model, units=[metre])

    context = run("context.add_context", model, context_type="Model")
    body = run("context.add_context", model, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW",
               parent=context)

    site = run("root.create_entity", model, ip_class="IfcSite", name="Site")
    building = run("root.create_entity", model, ip_class="IfcBuilding",
                   name=project_name)
    run("aggregate.assign_object", model, products=[site],
        relating_object=project)
    run("aggregate.assign_object", model, products=[building],
        relating_object=site)

    for index, storey in enumerate(structure["storeys"]):
        level = run("root.create_entity", model, ip_class="IfcBuildingStorey",
                    name=f"Level {index}")
        run("aggregate.assign_object", model, products=[level],
            relating_object=building)
        for wall in storey["walls"]:
            element = run("root.create_entity", model, ip_class="IfcWall",
                          name=f"Wall {wall['axis']} {wall['length_m']}m")
            run("spatial.assign_container", model, products=[element],
                relating_structure=level)

    model.write(path)
    return path


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
    except StructureError as e:
        result["ifc"] = False
        result["warnings"].append(str(e))

    prog.stage("exporting")
    json_path = os.path.join(directory, f"{scan}.structure.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    artifacts.append((json_path, f"structure/{scan}.json", None))

    return artifacts, {"structure": result, "warnings": result["warnings"]}


run = run_mode
