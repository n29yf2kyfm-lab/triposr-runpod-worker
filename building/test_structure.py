"""Tests for Structure Mode — point cloud to walls, slabs and storeys.

Built on a synthetic room of known size, so every number has a right answer
rather than a plausible one. The guards matter more than the geometry: an IFC
file looks authoritative and someone will build from it, so the interesting
tests are the ones where it refuses.

Run: python building/test_structure.py
"""
import os
import random
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import structure as S  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name if cond else f"{name}{' — ' + detail if detail else ''}")


# ---- a synthetic room: 5m x 4m x 2.4m, walls of ZERO thickness ------------
# The comment here used to say "walls 0.1m thick" while the generator below
# built single-plane walls with no thickness at all. That gap hid a real bug
# for the life of the module: trace_walls emitted one full-length wall per
# cell row THROUGH a wall, so 215mm masonry — the commonest UK external wall
# — came back as 20 walls and 5.3x the true centreline length, straight into
# the material order. A zero-thickness fixture is the one case that cannot
# trigger it. make_thick_room below exists so that case is covered.
W, D, H = 5.0, 4.0, 2.4
STEP = 0.04


def make_room(width=W, depth=D, height=H, step=STEP, z0=0.0):
    """Floor, ceiling and four single-plane walls. No thickness."""
    pts = []
    nx, ny = int(width / step), int(depth / step)
    for i in range(nx + 1):
        for j in range(ny + 1):
            x, y = i * step, j * step
            pts.append((x, y, z0))                 # floor
            pts.append((x, y, z0 + height))        # ceiling
    nz = int(height / step)
    for k in range(1, nz):
        z = z0 + k * step
        for i in range(nx + 1):
            pts.append((i * step, 0.0, z))         # front
            pts.append((i * step, depth, z))       # back
        for j in range(ny + 1):
            pts.append((0.0, j * step, z))         # left
            pts.append((width, j * step, z))       # right
    return pts


ROOM = make_room()


# ---- 1. preparation -------------------------------------------------------
check("1a the room has points", len(ROOM) > S.MIN_POINTS, str(len(ROOM)))

box = S.bounds(ROOM)
check("1b bounds are right",
      abs(box[3] - W) < 0.05 and abs(box[4] - D) < 0.05
      and abs(box[5] - H) < 0.05, str(box))

reduced = S.voxel_downsample(ROOM, 0.05)
check("1c downsampling reduces the count", len(reduced) < len(ROOM))
check("1d but keeps the shape",
      abs(S.bounds(reduced)[5] - H) < 0.1, str(S.bounds(reduced)))
# Occupancy, not sample count — otherwise the histogram describes how fast
# the operator walked rather than the building.
dupes = ROOM + ROOM[:1000]
check("1e duplicated points collapse to the same voxels",
      len(S.voxel_downsample(dupes, 0.05)) == len(reduced))
try:
    S.voxel_downsample(ROOM, 0)
    check("1f zero voxel refused", False)
except S.StructureError:
    check("1f zero voxel refused", True)


# ---- 2. THE scale guard ---------------------------------------------------
# A cloud in the wrong units segments perfectly and produces a house 30cm
# tall, with every wall in the right place relative to every other. Nothing
# looks wrong except the units, which is exactly why it must be caught here.
m = S.check_metric(reduced)
check("2a a real room passes", abs(m["height_m"] - H) < 0.1, str(m))

centimetres = [(x / 100, y / 100, z / 100) for x, y, z in reduced]
try:
    S.check_metric(centimetres)
    check("2b a cloud in centimetres is refused", False)
except S.StructureError as e:
    check("2b a cloud in centimetres is refused", "scale" in str(e), str(e))
    check("2c and names the likely cause", "centimetres" in str(e))

try:
    S.check_metric([(x * 100, y * 100, z * 100) for x, y, z in reduced])
    check("2d an absurdly large cloud is refused", False)
except S.StructureError:
    check("2d an absurdly large cloud is refused", True)

try:
    S.check_metric([(x * 60, y * 60, z) for x, y, z in reduced])
    check("2e a street-sized span is refused", False)
except S.StructureError as e:
    check("2e a street-sized span is refused", "street" in str(e), str(e))


# ---- 3. gravity alignment -------------------------------------------------
g = S.check_gravity_aligned(reduced)
check("3a an upright room passes", g["strongest_band_share"] > S.SLAB_SHARE,
      str(g))

# A tilted cloud does not fail loudly on its own — it produces sloping slabs
# and tapering walls, which reads as a badly built house.
import math  # noqa: E402
angle = math.radians(35)
tilted = [(x, y * math.cos(angle) - z * math.sin(angle),
           y * math.sin(angle) + z * math.cos(angle)) for x, y, z in reduced]
try:
    S.check_gravity_aligned(tilted)
    check("3b a badly tilted cloud is refused", False)
except S.StructureError as e:
    check("3b a badly tilted cloud is refused",
          "gravity-aligned" in str(e), str(e))

try:
    S.check_gravity_aligned([(0, 0, 0)] * 10)
    check("3c a sparse cloud is refused", False)
except S.StructureError as e:
    check("3c a sparse cloud is refused", "too sparse" in str(e))


# ---- 4. slabs and storeys -------------------------------------------------
slabs = S.find_slabs(reduced)
check("4a two slabs found", len(slabs) == 2, str(slabs))
check("4b floor at zero", abs(slabs[0]["z_m"]) < 0.1, str(slabs[0]))
check("4c ceiling at the right height", abs(slabs[1]["z_m"] - H) < 0.1,
      str(slabs[1]))

storeys = S.storeys_from_slabs(slabs)
check("4d one storey", len(storeys) == 1, str(storeys))
check("4e height recovered", abs(storeys[0]["height_m"] - H) < 0.1,
      str(storeys[0]["height_m"]))
check("4f and it is plausible for a UK house", storeys[0]["plausible"])

# Two storeys stacked.
TWO = make_room() + make_room(z0=2.7)
two_slabs = S.find_slabs(S.voxel_downsample(TWO, 0.05))
two_storeys = S.storeys_from_slabs(two_slabs)
check("4g a two-storey cloud gives more than one storey",
      len(two_storeys) >= 2, str(len(two_storeys)))

try:
    S.storeys_from_slabs(slabs[:1])
    check("4h one slab is not a storey", False)
except S.StructureError as e:
    check("4h one slab is not a storey", "floor and a ceiling" in str(e))

# A 1.2m gap is a mezzanine edge or a doubled slab, not a storey.
close = [{"z_m": 0.0, "points": 1000, "share": 0.1},
         {"z_m": 1.2, "points": 500, "share": 0.05}]
try:
    S.storeys_from_slabs(close)
    check("4i slabs too close together are not a storey", False)
except S.StructureError as e:
    check("4i slabs too close together are not a storey",
          "far enough apart" in str(e), str(e))

# A storey outside the UK domestic band is reported, not silently accepted.
tall = [{"z_m": 0.0, "points": 1000, "share": 0.1},
        {"z_m": 6.0, "points": 1000, "share": 0.1}]
check("4j an implausible storey height is flagged",
      not S.storeys_from_slabs(tall)[0]["plausible"])


# ---- 5. walls -------------------------------------------------------------
cells = S.wall_cells(reduced, storeys[0])
check("5a wall cells found", len(cells) > 50, str(len(cells)))

walls = S.trace_walls(cells)
check("5b walls traced", len(walls) >= 4, str(len(walls)))
longest = walls[0]["length_m"]
check("5c the longest run is about a room side",
      3.5 < longest < 5.5, str(longest))
check("5d runs are axis-aligned", all(w["axis"] in ("x", "y") for w in walls))
check("5e short stubs are dropped",
      all(w["length_m"] >= S.MIN_WALL_LENGTH_M for w in walls))

# THE discriminator: vertical extent, not density. A worktop is dense and
# short; a wall is floor to ceiling. This removes LOW furniture without any
# furniture model, and so without any training data.
#
# The block here was 0.8m tall and the comment called it a wardrobe. It is a
# worktop. The cut lands at about 1.30m (0.55 of a 2.1m working span), so
# 0.8m proves only that the mechanism runs — it never approached the
# threshold. Both cases are now tested, and the tall one is asserted to be
# MISSED, because that is the truth and the module warns about it rather
# than claiming a clean count.
worktop = list(reduced)
for i in range(30):
    for j in range(30):
        for k in range(20):          # 1.2 x 1.2 x 0.8m — below the cut
            worktop.append((2.0 + i * 0.04, 1.5 + j * 0.04, k * 0.04))
f_cells = S.wall_cells(worktop, storeys[0])
check("5f a 0.8m worktop is correctly rejected",
      abs(len(f_cells) - len(cells)) < len(cells) * 0.25,
      f"{len(cells)} -> {len(f_cells)}")

tall = list(reduced)
for i in range(30):
    for j in range(15):
        for k in range(50):          # 1.2 x 0.6 x 2.0m — a real wardrobe
            tall.append((2.0 + i * 0.04, 1.5 + j * 0.04, k * 0.04))
t_cells = S.wall_cells(tall, storeys[0])
check("5f2 a 2.0m wardrobe is NOT rejected — the honest limit",
      len(t_cells) > len(cells) * 1.05,
      f"{len(cells)} -> {len(t_cells)}: if this now passes, the docstring "
      f"claim about furniture can be strengthened")
check("5f3 and segment() warns rather than reporting a clean count",
      any("full-height" in w or "furniture" in w
          for w in S.segment(tall)["warnings"]),
      str(S.segment(tall)["warnings"]))

check("5g no cells means no walls", S.trace_walls({}) == [])

try:
    S.wall_cells(reduced, {"floor_z_m": 2.0, "ceiling_z_m": 1.0})
    check("5h an inverted storey is refused", False)
except S.StructureError:
    check("5h an inverted storey is refused", True)


# ---- 6. end to end --------------------------------------------------------
r = S.segment(ROOM)
check("6a segmentation completes", r["totals"]["storeys"] == 1, str(r["totals"]))
check("6b walls found", r["totals"]["walls"] >= 4)
check("6c floor area is about right",
      abs(r["storeys"][0]["floor_area_m2"] - W * D) < 3.0,
      str(r["storeys"][0]["floor_area_m2"]))
check("6d method says it is not RANSAC", "not RANSAC" in r["method"])
check("6e the axis-aligned limit is stated, not hidden",
      any("axis-aligned" in w for w in r["warnings"]), str(r["warnings"]))
check("6f checks are reported", "points_in" in r["checks"])

try:
    S.segment([])
    check("6g an empty cloud is refused", False)
except S.StructureError:
    check("6g an empty cloud is refused", True)


# ---- 7. PLY round trip ----------------------------------------------------
TMP = tempfile.gettempdir()

ascii_path = os.path.join(TMP, "t.ply")
with open(ascii_path, "w") as f:
    f.write("ply\nformat ascii 1.0\nelement vertex 3\n"
            "property float x\nproperty float y\nproperty float z\n"
            "end_header\n1.0 2.0 3.0\n4.0 5.0 6.0\n7.0 8.0 9.0\n")
got = S.read_ply(ascii_path)
check("7a ascii PLY read", len(got) == 3, str(got))
check("7b coordinates right", got[0] == (1.0, 2.0, 3.0), str(got[0]))

bin_path = os.path.join(TMP, "t2.ply")
with open(bin_path, "wb") as f:
    f.write(b"ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"property uchar red\nproperty uchar green\nproperty uchar blue\n"
            b"end_header\n")
    for p in ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)):
        f.write(struct.pack("<fff", *p) + bytes((255, 0, 0)))
got = S.read_ply(bin_path)
check("7c binary PLY read", len(got) == 2, str(got))
check("7d colours skipped, coordinates kept",
      abs(got[1][0] - 4.0) < 1e-5, str(got[1]))

# reconstruct.py writes the clouds this reads — prove the join.
import reconstruct as R  # noqa: E402
joined = os.path.join(TMP, "join.ply")
R.write_ply(joined, ROOM[:500])
back = S.read_ply(joined)
check("7e structure reads what reconstruct writes", len(back) == 500,
      str(len(back)))
check("7f and the geometry survives the round trip",
      abs(back[0][0] - ROOM[0][0]) < 1e-4, f"{back[0]} vs {ROOM[0]}")

for bad, label in [(os.path.join(TMP, "nope.ply"), "missing file"),
                   (ascii_path + ".txt", "not a PLY")]:
    if label == "not a PLY":
        with open(bad, "w") as f:
            f.write("not a ply at all\n")
    try:
        S.read_ply(bad)
        check(f"7g {label} refused", False)
    except S.StructureError:
        check(f"7g {label} refused", True)


# ---- 8. handler entry -----------------------------------------------------
class _Prog:
    def stage(self, *a, **k):
        pass


OUT = os.path.join(TMP, "structure-test")
cloud_path = os.path.join(TMP, "room.ply")
R.write_ply(cloud_path, ROOM)

arts, extra = S.run({"point_cloud_path": cloud_path, "scan_id": "t1"},
                    _Prog(), OUT)
res = extra["structure"]
check("8a end to end through the handler entry",
      res["totals"]["storeys"] == 1, str(res["totals"]))
check("8b a json artifact is written",
      any(a[0].endswith(".json") for a in arts), str(arts))
# 8c used to read `res["ifc"] in (True, False)`, which is vacuously true for
# any bool and would pass if the writer returned a constant. It was the only
# assertion guarding the IFC path, and underneath it the writer had NEVER
# run: `ip_class=` for `ifc_class=` in five places, and a submodule used
# without importing it. On a bare CI runner the ImportError branch fired and
# this assertion said yes. Every structure job on the deployed image died.
try:
    import ifcopenshell  # noqa: F401
    _HAVE_IFC = True
except ImportError:
    _HAVE_IFC = False

check("8c ifc reports what actually happened", res["ifc"] is _HAVE_IFC,
      f"ifc={res['ifc']} but ifcopenshell installed={_HAVE_IFC}: "
      f"{res['warnings']}")

if _HAVE_IFC:
    _ifc = [a[0] for a in arts if a[0].endswith(".ifc")]
    check("8d an IFC file is actually written", len(_ifc) == 1, str(arts))
    _text = open(_ifc[0]).read()
    # Metres, explicitly. The ifcopenshell default is millimetres, which
    # scales the building by 1000 and every quantity with it.
    check("8e the IFC is in metres", ".METRE." in _text and
          ".MILLI." not in _text)
    check("8f it contains the spatial tree",
          all(k in _text for k in ("IFCPROJECT", "IFCSITE", "IFCBUILDING(",
                                   "IFCBUILDINGSTOREY")), "spatial tree")
    check("8g every traced wall is in it",
          _text.count("IFCWALL") == res["totals"]["walls"],
          f"{_text.count('IFCWALL')} walls in IFC vs "
          f"{res['totals']['walls']} traced")
    check("8h the storey has a floor slab", "IFCSLAB" in _text)
    # A wall with no placement and no body is a name in a file: every viewer
    # opens it, shows nothing, and the file still looks authoritative.
    check("8i the walls have real geometry, not just names",
          _text.count("IFCEXTRUDEDAREASOLID") >= res["totals"]["walls"]
          and "IFCLOCALPLACEMENT" in _text,
          f"{_text.count('IFCEXTRUDEDAREASOLID')} solids")
else:
    check("8d and says why", any("ifcopenshell" in w for w in res["warnings"]),
          str(res["warnings"]))
    check("8e while keeping the segmentation", res["totals"]["walls"] >= 4)

# A broken IFC writer must never destroy a segmentation that succeeded. The
# StructureError-only catch let an AttributeError through to the handler,
# which returned {"error": ...} and threw the whole result away.
_real_write = S.write_ifc
S.write_ifc = lambda *a, **k: (_ for _ in ()).throw(AttributeError("boom"))
try:
    _arts, _extra = S.run({"point_cloud_path": cloud_path, "scan_id": "t2"},
                          _Prog(), OUT)
    _res = _extra["structure"]
    check("8j a crashing IFC writer does not lose the segmentation",
          _res["totals"]["walls"] >= 4 and _res["ifc"] is False,
          str(_res.get("totals")))
    check("8k and the failure is reported as a warning",
          any("IFC export failed" in w for w in _res["warnings"]),
          str(_res["warnings"]))
except Exception as e:
    check("8j a crashing IFC writer does not lose the segmentation", False,
          f"{type(e).__name__} escaped: {e}")
finally:
    S.write_ifc = _real_write

try:
    S.run({}, _Prog(), OUT)
    check("8f no cloud is refused", False)
except S.StructureError as e:
    check("8f no cloud is refused", "point cloud" in str(e))

# Validation before any network work, as everywhere else in this worker.
try:
    S.run({"point_cloud_url": "file:///etc/passwd"}, _Prog(), OUT)
    check("8g a local-file URL is refused", False)
except Exception as e:
    check("8g a local-file URL is refused",
          "http" in str(e).lower() or "scheme" in str(e).lower(), str(e)[:70])


# ---- 9. walls that have a thickness --------------------------------------
# Every assertion above ran against zero-thickness walls, which is the one
# case that cannot expose the bug: each 50mm cell row through a real wall was
# traced as its own full-length wall.

def make_thick_room(width=5.0, depth=4.0, height=2.4, thickness=0.215,
                    step=0.03, ox=0.0, oy=0.0):
    """A room whose walls have two faces, the way a scan sees them."""
    pts = []
    faces = (lambda a: [a] if thickness <= 0
             else [a - thickness / 2, a + thickness / 2])
    zs = [k * step for k in range(int(height / step) + 1)]
    xs = [i * step for i in range(int(width / step) + 1)]
    ys = [j * step for j in range(int(depth / step) + 1)]
    for z in zs:
        for x in xs:
            for y in faces(0.0) + faces(depth):
                pts.append((ox + x, oy + y, z))
        for y in ys:
            for x in faces(0.0) + faces(width):
                pts.append((ox + x, oy + y, z))
    for x in xs:
        for y in ys:
            pts.append((ox + x, oy + y, 0.0))
            pts.append((ox + x, oy + y, height))
    random.Random(0).shuffle(pts)
    return pts


# True centreline perimeter of a 5x4 room is 18.0m at every thickness.
for _t, _label in [(0.0, "single-plane"), (0.1, "100mm stud"),
                   (0.215, "215mm masonry"), (0.3, "300mm cavity")]:
    _r = S.segment(make_thick_room(thickness=_t), voxel_m=0.02)
    _st = _r["storeys"][0]
    check(f"9a {_label}: four walls, not one per cell row",
          len(_st["walls"]) == 4, f"{len(_st['walls'])} walls")
    check(f"9b {_label}: wall length within 5% of the true 18.0m",
          abs(_st["wall_length_m"] - 18.0) <= 0.9,
          f"{_st['wall_length_m']}m")
    check(f"9c {_label}: floor area within 5% of the true 20.0m2",
          abs(_st["floor_area_m2"] - 20.0) <= 1.0,
          f"{_st['floor_area_m2']}m2")

# Thickness is recovered when the scan saw both faces, and that is worth
# having on its own — no drawing take-off can measure it.
_r = S.segment(make_thick_room(thickness=0.215), voxel_m=0.02)
_thk = [w["thickness_m"] for w in _r["storeys"][0]["walls"]]
check("9d a scan that saw both faces recovers the thickness",
      all(0.19 <= t <= 0.28 for t in _thk), str(_thk))

# An L-shaped plan — every UK house with a rear extension. The walls were
# always traced correctly; the area reduction was a bounding box, reported
# as "the wall envelope", and read 42.65 against a true 33.0.
_l = S.segment(make_thick_room(6.0, 4.0, thickness=0.0)
               + make_thick_room(3.0, 3.0, thickness=0.0, oy=4.0),
               voxel_m=0.02)
_ls = _l["storeys"][0]
check("9e an L-shaped plan is not measured as its bounding box",
      abs(_ls["floor_area_m2"] - 33.0) <= 1.7,
      f"{_ls['floor_area_m2']}m2 against a true 33.0 "
      f"(a bounding box gives 42.0)")

# The frame services mode needs. Its error message said "structure mode
# produces it" while structure mode emitted start, end, length_m and axis.
_w = _r["storeys"][0]["walls"][0]
for _key in ("origin", "direction", "plane", "width_m", "height_m",
             "thickness_m"):
    check(f"9f a wall carries {_key} for services mode", _key in _w,
          str(sorted(_w)))
check("9g the plane normal is a unit vector",
      abs(math.hypot(_w["plane"][0], _w["plane"][1]) - 1.0) < 1e-6,
      str(_w["plane"]))
check("9h the plane passes through the wall origin",
      abs(_w["plane"][0] * _w["origin"][0] + _w["plane"][1] * _w["origin"][1]
          + _w["plane"][3]) < 1e-3, str(_w["plane"]))
check("9i origin sits at floor level",
      abs(_w["origin"][2] - _r["storeys"][0]["floor_z_m"]) < 1e-6)

# check_gravity_aligned took the first N points in FILE order. A PLY written
# floor-block-first made a perfectly good room look flat, and the cloud was
# refused as not gravity-aligned.
_ordered = make_thick_room(thickness=0.1)
_ordered.sort(key=lambda p: p[2])          # every floor point first
try:
    _r = S.segment(_ordered, voxel_m=0.02)
    check("9j a floor-first point order is still accepted",
          _r["totals"]["walls"] >= 4, str(_r["totals"]))
except S.StructureError as e:
    check("9j a floor-first point order is still accepted", False, str(e))


# ---- 10. an open doorway must not drain the floor --------------------------
# A real scan of a room with an open doorway has points only above the door
# head in the opening, so the traced front wall has a 0.9m gap. The border
# flood used to pour through it and mark the whole room outside: 0.43 m2
# against a true 20.0, delivered silently. Gaps up to a door's width are
# bridged before flooding, and a fill that still collapses is delivered
# WITH a warning, never bare.
def make_doorway_room(width=W, depth=D, height=H, step=STEP,
                      door_at=2.0, door_w=0.9, head=2.0):
    """make_room, with an ordinary open doorway in the front wall."""
    pts = []
    nx, ny = int(width / step), int(depth / step)
    for i in range(nx + 1):
        for j in range(ny + 1):
            x, y = i * step, j * step
            pts.append((x, y, 0.0))
            pts.append((x, y, height))
    nz = int(height / step)
    for k in range(1, nz):
        z = k * step
        for i in range(nx + 1):
            x = i * step
            if not (door_at <= x <= door_at + door_w and z < head):
                pts.append((x, 0.0, z))            # front, gap at the door
            pts.append((x, depth, z))
        for j in range(ny + 1):
            pts.append((0.0, j * step, z))
            pts.append((width, j * step, z))
    return pts


_d = S.segment(make_doorway_room(), voxel_m=0.02)
_ds = _d["storeys"][0]
check("10a a room with an open doorway keeps its floor area",
      abs(_ds["floor_area_m2"] - 20.0) <= 1.5, f"{_ds['floor_area_m2']}m2")
check("10b and carries no collapse warning",
      not _ds.get("floor_area_note"), str(_ds.get("floor_area_note")))

# Walls that genuinely do not enclose anything: the number still comes back,
# but with the warning riding on it — a wildly wrong area delivered with
# confidence is the exact thing this module refuses to do.
_a, _note = S._envelope_area([
    {"start": (0.0, 0.0), "end": (5.0, 0.0)},
    {"start": (0.0, 4.0), "end": (5.0, 4.0)}])
check("10c an unclosed trace warns instead of asserting",
      _note is not None and "NOT trustworthy" in _note, str(_note))
check("10d a sealed room still returns no note",
      S._envelope_area(S.segment(make_thick_room(thickness=0.0),
                                 voxel_m=0.02)["storeys"][0]["walls"])[1]
      is None)


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
