"""Tests for reading the facade off a photo, and applying what was read.

The parse, the mapping and the wall surgery are all deterministic and
network-free — the only unverifiable link is the vision model itself, which
is why everything it returns passes through the validation tested here
before a single wall changes.

Run: python building/test_imagery.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import imagery as I  # noqa: E402
import model3d as M  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. parsing what a vision model actually returns ------------------------
good = '''Here is the JSON you asked for:
{"storeys": 2, "finish": "brick", "chimney": true,
 "openings": [
   {"floor": 0, "kind": "door", "x0": 0.44, "x1": 0.52},
   {"floor": 0, "kind": "bay",  "x0": 0.05, "x1": 0.35},
   {"floor": 1, "kind": "window", "x0": 0.10, "x1": 0.30},
   {"floor": 1, "kind": "window", "x0": 0.60, "x1": 0.80}
 ]}'''
r = I.parse_reading(good)
check("1a JSON is found inside prose", r is not None)
check("1b all four openings survive", len(r["openings"]) == 4,
      str(r and len(r["openings"])))
check("1c the chimney is recorded", r["chimney"] is True)
check("1d the finish is recorded", r["finish"] == "brick")

# The validation that stands between the model's imagination and the walls.
bad = '''{"storeys": 2, "openings": [
  {"floor": 0, "kind": "window", "x0": 0.9, "x1": 0.4},
  {"floor": 0, "kind": "window", "x0": -0.2, "x1": 0.1},
  {"floor": 0, "kind": "window", "x0": 0.10, "x1": 0.11},
  {"floor": 0, "kind": "window", "x0": 0.05, "x1": 0.95},
  {"floor": 1, "kind": "door",  "x0": 0.4, "x1": 0.5},
  {"floor": 0, "kind": "portcullis", "x0": 0.4, "x1": 0.5},
  {"floor": 0, "kind": "window", "x0": 0.30, "x1": 0.45}
]}'''
r2 = I.parse_reading(bad)
check("1e reversed, out-of-range, sliver, giant, first-floor-door and "
      "unknown kinds are ALL dropped",
      r2 is not None and len(r2["openings"]) == 1, str(r2))
check("1f the one sane window survives",
      r2["openings"][0]["x0"] == 0.30)

check("1g no JSON at all gives None", I.parse_reading("cannot help") is None)
check("1h unreadable flag gives None",
      I.parse_reading('{"unreadable": true}') is None)
check("1i nothing usable gives None, not an empty reading",
      I.parse_reading('{"storeys": 2, "openings": []}') is None)

# --- 2. fractions to wall openings ------------------------------------------
ops, bays = I.to_wall_openings(r, 10.0)
check("2a the bay comes out as geometry, not a hole",
      len(bays) == 1 and abs(bays[0]["x"] - 0.5) < 1e-6
      and abs(bays[0]["width"] - 3.0) < 1e-6, str(bays))
check("2b three wall openings", len(ops) == 3, str(len(ops)))
door = [o for o in ops if o["kind"] == "door"][0]
check("2c the door lands where the photo put it",
      abs(door["along"] - 4.4) < 1e-6 and door["level"] == 0, str(door))
check("2d door width is capped at a leaf", door["width"] <= 1.2)
win1 = [o for o in ops if o["kind"] == "window" and o["level"] == 1]
check("2e first-floor windows carry their level", len(win1) == 2)
check("2f windows carry a sill", all(o["sill"] > 0 for o in win1))

# --- 3. the wall surgery ----------------------------------------------------
model = M.build([M.Room("h", 0.0, 0.0, 10.0, 6.0, 2.75)], storeys=2,
                storey_height=2.75)
before_doors = model["totals"]["doors"]
res = M.apply_facade_openings(model, ops, facade_y=0.0)
check("3a everything applied", res["applied"] == 3, str(res))
front = [w for w in model["walls"] if w["external"]
         and abs(w["start"][1]) < 1e-6 and abs(w["end"][1]) < 1e-6]
front_ops = [o for w in front for o in w["openings"]]
check("3b the rule openings on the front are gone, the photo's are in",
      len(front_ops) == 3, str(len(front_ops)))
check("3c totals were recomputed, not left stale",
      model["totals"]["doors"] >= 1
      and model["totals"]["windows"] != before_doors,
      str(model["totals"]))

# A reading with no door must not produce a doorless house.
model2 = M.build([M.Room("h", 0.0, 0.0, 10.0, 6.0, 2.75)], storeys=2,
                 storey_height=2.75)
no_door = [o for o in ops if o["kind"] != "door"]
res2 = M.apply_facade_openings(model2, no_door, facade_y=0.0)
check("3d the rule door survives when the photo shows none",
      res2["door_preserved"] and model2["totals"]["doors"] >= 1, str(res2))

# Overlapping and out-of-wall openings are refused, not stacked.
# The reading carries its own door, so no rule-placed door is preserved
# into the count. Without that this test was really measuring where the
# rule happened to park the front door, and it moved the moment the rule
# placed more than one window per wall.
clash = [{"kind": "window", "along": 2.0, "width": 2.0, "height": 1.2,
          "sill": 0.9, "level": 0},
         {"kind": "window", "along": 3.0, "width": 2.0, "height": 1.2,
          "sill": 0.9, "level": 0},
         {"kind": "door", "along": 7.0, "width": 0.9, "height": 2.0,
          "sill": 0.0, "level": 0},
         {"kind": "window", "along": 30.0, "width": 2.0, "height": 1.2,
          "sill": 0.9, "level": 0}]
model3 = M.build([M.Room("h", 0.0, 0.0, 10.0, 6.0, 2.75)], storeys=1,
                 storey_height=2.75)
res3 = M.apply_facade_openings(model3, clash, facade_y=0.0)
check("3e an overlap and an out-of-wall opening are skipped",
      res3["applied"] == 2 and res3["skipped"] == 2, str(res3))
check("3e2 and no rule door was smuggled in on top",
      res3["door_preserved"] is False, str(res3))

# No wall on the facade line: refuse with a reason, change nothing.
model4 = M.build([M.Room("h", 0.0, 5.0, 10.0, 6.0, 2.75)], storeys=1,
                 storey_height=2.75)
res4 = M.apply_facade_openings(model4, ops, facade_y=0.0)
check("3f a missing facade wall is a named refusal",
      res4["applied"] == 0 and "why" in res4, str(res4))

# The GLB must reflect the surgery — the exporter reads the same dicts.
groups = M._glb_mesh(model)
check("3g the exported mesh sees the new openings",
      "glass" in groups and len(groups["glass"][0]) > 0)



# A two-storey bay whose UPPER read starts further left than the lower one:
# the merge must keep the full span of both. The first version computed the
# merged right edge from b["x"] after b["x"] had already been moved left, so
# the bay came out short by exactly that difference.
_two_floor_left = {"storeys": 2, "finish": "brick", "chimney": False,
                   "openings": [
                       {"floor": 0, "kind": "bay", "x0": 0.10, "x1": 0.30},
                       {"floor": 1, "kind": "bay", "x0": 0.05, "x1": 0.28}]}
_ops, _bays = I.to_wall_openings(_two_floor_left, 8.0)
check("9a overlapping bays merge to one", len(_bays) == 1, str(_bays))
check("9b the merged bay keeps the leftmost edge",
      abs(_bays[0]["x"] - 0.4) < 0.01, str(_bays[0]["x"]))
check("9c and the rightmost edge — not the one it just overwrote",
      abs((_bays[0]["x"] + _bays[0]["width"]) - 2.4) < 0.01,
      str(_bays[0]["x"] + _bays[0]["width"]))
check("9d and it is two storeys tall", _bays[0]["storeys"] == 2)

print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
