"""Tests for Structure Mode — point cloud to walls, slabs and storeys.

Built on a synthetic room of known size, so every number has a right answer
rather than a plausible one. The guards matter more than the geometry: an IFC
file looks authoritative and someone will build from it, so the interesting
tests are the ones where it refuses.

Run: python building/test_structure.py
"""
import os
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


# ---- a synthetic room: 5m x 4m x 2.4m, walls 0.1m thick -------------------
W, D, H = 5.0, 4.0, 2.4
STEP = 0.04


def make_room(width=W, depth=D, height=H, step=STEP, z0=0.0):
    """Floor, ceiling and four walls. Dense enough to be realistic."""
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

# THE discriminator: vertical extent, not density. A wardrobe is dense and
# short; a wall is floor to ceiling. This is what removes furniture without
# any furniture model, and so without any training data.
furniture = list(reduced)
for i in range(30):
    for j in range(30):
        for k in range(20):          # 1.2m x 1.2m x 0.8m block mid-room
            furniture.append((2.0 + i * 0.04, 1.5 + j * 0.04, k * 0.04))
f_cells = S.wall_cells(furniture, storeys[0])
check("5f a full-height wall count is barely changed by furniture",
      abs(len(f_cells) - len(cells)) < len(cells) * 0.25,
      f"{len(cells)} -> {len(f_cells)}")

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
# ifcopenshell is not installed on a bare test runner, and that must degrade
# rather than lose the segmentation that already succeeded.
check("8c missing ifcopenshell degrades, it does not crash",
      res["ifc"] in (True, False))
if not res["ifc"]:
    check("8d and says why", any("ifcopenshell" in w for w in res["warnings"]),
          str(res["warnings"]))
    check("8e while keeping the segmentation", res["totals"]["walls"] >= 4)

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


# ==========================================================================
print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
