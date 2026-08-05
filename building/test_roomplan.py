"""Tests for RoomPlan ingest — a phone scan becomes the same model a
drawing does.

The fixture is a synthetic CapturedRoom export: a 4.2m x 3.6m room whose
walls are ROTATED 17 DEGREES in world space, because that is what a real
scan looks like — RoomPlan's axes are wherever the phone pointed when the
session started, never the building's. Every geometric assertion here is
therefore also an assertion that the de-rotation works: if it did not, no
wall would be axis-aligned and every length would come out as a projection.

Network-free, GPU-free, stdlib only.

Run: python building/test_roomplan.py
"""
import json
import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import roomplan as R  # noqa: E402
import model3d as M   # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(
        name + (f" [{detail}]" if detail and not cond else ""))
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- fixture ----------------------------------------------------------------
# A room 4.2m (x) by 3.6m (y in plan), walls 2.4m high, rotated by THETA
# about the world Y axis and shifted, exactly as ARKit would report it.
# Column-major 4x4: columns are the local x, y, z axes then translation.

THETA = math.radians(17.0)
SHIFT = (5.0, 0.0, -2.0)          # world x, y, z


def _wall(cx_plan, cy_plan, run_deg, length, height=2.4, ident=None):
    """A RoomPlan wall surface at a plan position/heading, pre-rotation."""
    yaw = math.radians(run_deg) + THETA
    # Rotate the plan position by THETA in plan space, then map plan (x, y)
    # to world (x, -z).
    px = cx_plan * math.cos(THETA) - cy_plan * math.sin(THETA)
    py = cx_plan * math.sin(THETA) + cy_plan * math.cos(THETA)
    wx, wz = px + SHIFT[0], -py + SHIFT[2]
    dx, dy = math.cos(yaw), math.sin(yaw)          # plan direction
    lx, lz = dx, -dy                               # world local-x axis
    # local y is world up; local z completes the frame (unused by parser)
    m = [lx, 0.0, lz, 0.0,
         0.0, 1.0, 0.0, 0.0,
         -lz, 0.0, lx, 0.0,
         wx, 1.2 + SHIFT[1], wz, 1.0]
    return {"identifier": ident, "category": {"wall": {}},
            "dimensions": [length, height, 0.0], "transform": m}


def _opening(kind, cx_plan, cy_plan, width, height, base_y, parent):
    px = cx_plan * math.cos(THETA) - cy_plan * math.sin(THETA)
    py = cx_plan * math.sin(THETA) + cy_plan * math.cos(THETA)
    wx, wz = px + SHIFT[0], -py + SHIFT[2]
    m = [1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         wx, base_y + height / 2.0, wz, 1.0]
    return {"category": {kind: {}}, "dimensions": [width, height, 0.0],
            "transform": m, "parentIdentifier": parent}


def _floor():
    corners = []
    for cx, cy in [(0, 0), (4.2, 0), (4.2, 3.6), (0, 3.6)]:
        px = cx * math.cos(THETA) - cy * math.sin(THETA)
        py = cx * math.sin(THETA) + cy * math.cos(THETA)
        corners.append([px + SHIFT[0], 0.0, -py + SHIFT[2]])
    return {"category": {"floor": {}}, "dimensions": [4.2, 3.6, 0.0],
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "polygonCorners": corners}


EXPORT = {
    "version": 2,
    "walls": [
        _wall(2.1, 0.0, 0, 4.2, ident="w-south"),
        _wall(4.2, 1.8, 90, 3.6, ident="w-east"),
        _wall(2.1, 3.6, 0, 4.2, ident="w-north"),
        _wall(0.0, 1.8, 90, 3.6, ident="w-west"),
    ],
    "doors": [
        _opening("door", 1.0, 0.0, 0.838, 1.981, 0.02, "w-south"),
    ],
    "windows": [
        _opening("window", 2.1, 3.6, 1.2, 1.2, 0.9, "w-north"),
    ],
    "openings": [],
    "floors": [_floor()],
    "objects": [],
}


# --- 1. parsing and de-rotation ---------------------------------------------

parsed = R.parse(EXPORT)

check("1a four walls parsed", len(parsed["walls"]) == 4)
check("1b the 17-degree scan rotation is detected",
      abs(abs(parsed["rotation_deg"]) - 17.0) < 0.5,
      str(parsed["rotation_deg"]))
_axis = sum(1 for w in parsed["walls"]
            if w["dx"] in (-1.0, 0.0, 1.0) and w["dy"] in (-1.0, 0.0, 1.0))
check("1c every wall is axis-aligned after de-rotation", _axis == 4,
      str(_axis))
_lens = sorted(round(w["length"], 3) for w in parsed["walls"])
check("1d wall lengths survive the rotation exactly",
      _lens == [3.6, 3.6, 4.2, 4.2], str(_lens))
check("1e de-rotation is reported, not silent",
      any("de-rotated" in w for w in parsed["warnings"]))

# --- 2. the model ------------------------------------------------------------

model = R.to_model(parsed)

check("2a wall run is the room perimeter",
      abs(model["totals"]["wall_length_m"] - 15.6) < 0.01,
      str(model["totals"]["wall_length_m"]))
check("2b floor area comes from the scanned polygon, not a bbox",
      abs(model["totals"]["floor_area_m2"] - 15.12) < 0.01,
      str(model["totals"]["floor_area_m2"]))
check("2c one door, one window", model["totals"]["doors"] == 1
      and model["totals"]["windows"] == 1,
      f"{model['totals']['doors']}/{model['totals']['windows']}")
check("2d no roof is invented for an interior scan",
      model["roof"] is None and model["totals"]["roof_sloped_area_m2"] is None)
check("2e the LiDAR-estimate caveat is on the model",
      any("LiDAR" in w for w in model["warnings"]))

# the door landed on the south wall at the right offset with a zero sill
_south = next(w for w in model["walls"]
              if any(o["kind"] == "door" for o in w["openings"]))
_door = next(o for o in _south["openings"] if o["kind"] == "door")
check("2f door sill is zero — threshold noise is not a raised opening",
      _door["sill"] == 0.0, str(_door["sill"]))
check("2g door offset survives rotation",
      abs(_door["along"] - (1.0 - 0.838 / 2)) < 0.05, str(_door["along"]))

_window = next(o for w in model["walls"] for o in w["openings"]
               if o["kind"] == "window")
check("2h window sill survives as 0.9m",
      abs(_window["sill"] - 0.9) < 0.05, str(_window["sill"]))

# net wall area: gross 15.6 * 2.4 minus the two openings
_expect = 15.6 * 2.4 - 0.838 * 1.981 - 1.2 * 1.2
check("2i net wall area subtracts the openings",
      abs(model["totals"]["wall_area_net_m2"] - _expect) < 0.05,
      f"{model['totals']['wall_area_net_m2']} vs {_expect:.2f}")

check("2j no wall claims to be external — a scan cannot know",
      all(not w["external"] for w in model["walls"]))

# --- 3. the exports run on it ------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    obj_path = os.path.join(td, "scan.obj")
    M.write_obj(model, obj_path)
    check("3a OBJ writes", os.path.getsize(obj_path) > 500)

    glb_path = os.path.join(td, "scan.glb")
    M.write_glb(model, glb_path)
    with open(glb_path, "rb") as f:
        blob = f.read()
    magic, version, total = struct.unpack("<III", blob[:12])
    check("3b GLB magic/version/length", magic == 0x46546C67
          and version == 2 and total == len(blob))
    jlen, jtype = struct.unpack("<II", blob[12:20])
    gltf = json.loads(blob[20:20 + jlen].decode("utf-8"))
    # No roof: the model's top is the wall height, and a Y-up swap would
    # put the 4.2m run where the 2.4m height should be.
    ymax = max(a["max"][1] for a in gltf["accessors"]
               if a.get("type") == "VEC3" and "max" in a)
    check("3c GLB tallest point is the wall height, not a wall length",
          abs(ymax - 2.4) < 0.01, str(ymax))
    check("3d GLB has glass and door primitives",
          {"glass", "door"} <= {gltf["materials"][p["material"]]["name"]
                                for mesh in gltf["meshes"]
                                for p in mesh["primitives"]})

# --- 4. refusals -------------------------------------------------------------

try:
    R.parse({"version": 2, "walls": []})
    check("4a empty scan is refused", False)
except R.RoomPlanError as e:
    check("4a empty scan is refused", "no walls" in str(e))

try:
    R.parse("{not json")
    check("4b malformed JSON is refused cleanly", False)
except R.RoomPlanError:
    check("4b malformed JSON is refused cleanly", True)

_bad = {"version": 2, "walls": [{"category": {"wall": {}},
                                "dimensions": [4200.0, 2.4, 0.0],
                                "transform": [1, 0, 0, 0, 0, 1, 0, 0,
                                              0, 0, 1, 0, 0, 1.2, 0, 1]}]}
try:
    R.parse(_bad)
    check("4c a 4200m wall is a unit error, refused", False)
except R.RoomPlanError as e:
    check("4c a 4200m wall is a unit error, refused", "outside" in str(e))

# --- 5. an off-axis wall stays true and is flagged ---------------------------

_splay = dict(EXPORT)
_splay["walls"] = EXPORT["walls"] + [
    _wall(2.1, 1.8, 40, 2.0, ident="w-splay")]
_p5 = R.parse(_splay)
_w5 = next(w for w in _p5["walls"] if w["id"] == "w-splay")
_ang5 = math.degrees(math.atan2(_w5["dy"], _w5["dx"])) % 90
check("5a a 40-degree splay is not snapped to an axis",
      5.0 < _ang5 < 85.0, str(_ang5))
check("5b splay length survives untouched",
      abs(_w5["length"] - 2.0) < 1e-6, str(_w5["length"]))
check("5c off-axis wall is flagged for the OBJ's sake",
      any("off-axis" in w for w in _p5["warnings"]))

# --- 6. proximity attach when parentIdentifier is missing --------------------

_orphan = json.loads(json.dumps(EXPORT))
for d in _orphan["doors"] + _orphan["windows"]:
    d.pop("parentIdentifier", None)
_m6 = R.to_model(R.parse(_orphan))
check("6a openings attach by proximity without parentIdentifier",
      _m6["totals"]["doors"] == 1 and _m6["totals"]["windows"] == 1,
      f"{_m6['totals']['doors']}/{_m6['totals']['windows']}")

# --- 7. a file path works and a missing one is refused -----------------------

with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "room.json")
    with open(p, "w") as f:
        json.dump(EXPORT, f)
    _m7 = R.to_model(R.parse(p))
    check("7a a JSON file on disk parses the same",
          _m7["totals"]["walls"] == 4)
    check("7b fetch_export returns the path form",
          R.fetch_export({"roomplan_path": p, "roomplan_url": None}, td) == p)
try:
    R.fetch_export({"roomplan_path": "/no/such/file", "roomplan_url": None},
                   "/tmp")
    check("7c a missing roomplan_path is refused", False)
except R.RoomPlanError:
    check("7c a missing roomplan_path is refused", True)


# --- 8. the joints: parse_job -> run_mode, the path a real job takes ---------
# Every module in this repo has now been bitten at least once by a bug that
# lived between two individually-tested pieces, so the scan path is exercised
# exactly as the handler drives it: raw job body through the validator,
# validated spec through run_mode, artifacts out.

import validation  # noqa: E402


class _Prog:
    def stage(self, *_a, **_k):
        pass


with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "room.json")
    with open(p, "w") as f:
        json.dump(EXPORT, f)

    spec8 = validation.parse_job({"mode": "model", "roomplan_path": p,
                                  "scan_id": "scan8"})
    check("8a parse_job accepts a scan-only model job",
          spec8["roomplan_path"] == p and spec8["plan"] is None)

    artifacts, out = M.run_mode(spec8, _Prog(), td)
    names = sorted(os.path.basename(a[0]) for a in artifacts)
    check("8b run_mode produces OBJ, GLB and JSON from the scan",
          "scan8.obj" in names and "scan8.glb" in names
          and "scan8.model.json" in names, str(names))
    check("8c the model came from the scan, not a plan",
          out["model"].get("source") == "roomplan")
    check("8d quantities flow through the joint",
          out["model"]["totals"]["doors"] == 1
          and abs(out["model"]["totals"]["wall_length_m"] - 15.6) < 0.01)

    try:
        validation.parse_job({"mode": "model"})
        check("8e a model job with neither plan nor scan is refused", False)
    except validation.InputError as e:
        check("8e a model job with neither plan nor scan is refused",
              "roomplan" in str(e))

    both = validation.parse_job({
        "mode": "model", "roomplan_path": p, "scan_id": "scan8b",
        "plan": {"rooms": [{"name": "Room", "x": 0, "y": 0,
                            "width_m": 4.0, "depth_m": 3.0}]}})
    _a8, out8 = M.run_mode(both, _Prog(), td)
    check("8f plan beats scan when both are sent, and says so",
          any("Both a typed plan and a RoomPlan scan" in w
              for w in out8["model"]["warnings"])
          and out8["model"].get("source") != "roomplan")


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
