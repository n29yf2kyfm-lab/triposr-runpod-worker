"""Tests for the IFC export — written because an audit caught it empty.

An independent audit executed write_ifc and found seven walls and four
spaces on one storey at z=0: no slabs, no roof, no doors, no windows, no
openings, no upper floors — while the GLB from the same model carried all of
them. Every test here parses the WRITTEN FILE back with ifcopenshell and
counts what is actually in it, because trusting the writer is exactly the
mistake that shipped the husk.

Run: python building/test_ifc.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import model3d as M  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


try:
    import ifcopenshell
except ImportError:
    print("note: ifcopenshell not installed — nothing to test here")
    sys.exit(0)


# The model the audit used, plus the shapes that exposed the gaps: two
# storeys, a single-storey extension with a flat cap, and a pitched roof.
rooms = [
    M.Room("house", 0.0, 0.0, 8.0, 6.0, 2.75),
    M.Room("extension", 0.0, 6.0, 8.0, 3.0, 2.4, kind="extension",
           storeys=1),
]
model = M.build(rooms, storeys=2, storey_height=2.75,
                roof={"pitch_deg": 38.0, "kind": "hipped"})

td = tempfile.mkdtemp()
path = os.path.join(td, "t.ifc")
M.write_ifc(model, path)
f = ifcopenshell.open(path)


def by(cls):
    return f.by_type(cls)


# --- 1. every storey exists, at its real height -----------------------------
st = sorted(by("IfcBuildingStorey"), key=lambda s: s.Elevation or 0)
check("1a two storeys written", len(st) == 2, str(len(st)))
check("1b ground floor at 0", abs((st[0].Elevation or 0) - 0.0) < 1e-6)
check("1c first floor at the storey height",
      abs((st[1].Elevation or 0) - 2.75) < 1e-6, str(st[1].Elevation))

# --- 2. walls on the levels they exist on, at that level's z ----------------
walls = by("IfcWall")
per_level = {}
for w in model["walls"]:
    for lv in range(2):
        if M._wall_on_level(w, lv) and w["length_m"] > 0:
            per_level[lv] = per_level.get(lv, 0) + 1
check("2a wall count matches the model level by level",
      len(walls) == per_level.get(0, 0) + per_level.get(1, 0),
      f"ifc {len(walls)} vs model {per_level}")
l1 = [w for w in walls if "L1" in (w.Name or "")]
check("2b the extension's walls are NOT repeated on the first floor",
      0 < len(l1) < per_level.get(0, 0), f"L1 walls {len(l1)}")
zs = set()
for w in l1:
    m = ifcopenshell.util.placement.get_local_placement(w.ObjectPlacement) \
        if hasattr(ifcopenshell, "util") else None
    if m is not None:
        zs.add(round(float(m[2][3]), 3))
if zs:
    check("2c first-floor walls actually sit at first-floor z",
          zs == {2.75}, str(zs))
else:
    import ifcopenshell.util.placement
    for w in l1:
        m = ifcopenshell.util.placement.get_local_placement(w.ObjectPlacement)
        zs.add(round(float(m[2][3]), 3))
    check("2c first-floor walls actually sit at first-floor z",
          zs == {2.75}, str(zs))

# --- 3. openings, doors and windows -----------------------------------------
doors_model = model["totals"]["doors"]
windows_model = model["totals"]["windows"]
check("3a a door exists in the file", len(by("IfcDoor")) >= 1,
      str(len(by("IfcDoor"))))
check("3b windows exist in the file", len(by("IfcWindow")) >= 1,
      str(len(by("IfcWindow"))))
check("3c door count matches the take-off",
      len(by("IfcDoor")) == doors_model,
      f"ifc {len(by('IfcDoor'))} vs takeoff {doors_model}")
check("3d window count matches the take-off",
      len(by("IfcWindow")) == windows_model,
      f"ifc {len(by('IfcWindow'))} vs takeoff {windows_model}")
check("3e every door and window has an opening",
      len(by("IfcOpeningElement"))
      == len(by("IfcDoor")) + len(by("IfcWindow")))
check("3f openings actually void their walls",
      len(by("IfcRelVoidsElement")) == len(by("IfcOpeningElement")))
check("3g fillings actually fill their openings",
      len(by("IfcRelFillsElement")) == len(by("IfcOpeningElement")))

# --- 4. slabs, caps and the roof --------------------------------------------
slabs = by("IfcSlab")
floors = [s for s in slabs if s.PredefinedType == "FLOOR"]
caps = [s for s in slabs if s.PredefinedType == "ROOF"]
# Floor plates follow the ROOMS on each level, not the bounding box: the
# two-storey house contributes one plate per storey and the single-storey
# extension its own — a box-per-storey put a phantom plate over the
# extension's open air at level 1.
check("4a a floor slab per room-covered plate, not per bounding box",
      len(floors) == 3, str(len(floors)))
check("4b the extension's flat cap is in the file", len(caps) == 1,
      str(len(caps)))
check("4c the pitched roof is in the file", len(by("IfcRoof")) == 1,
      str(len(by("IfcRoof"))))
roof_el = by("IfcRoof")[0]
rep = roof_el.Representation.Representations[0]
check("4d the roof carries real geometry, not a placeholder",
      rep.RepresentationType == "SurfaceModel"
      and len(rep.Items[0].FbsmFaces[0].CfsFaces) >= 4,
      rep.RepresentationType)

# --- 5. spaces land on their own storeys ------------------------------------
spaces = by("IfcSpace")
check("5a every room is a space", len(spaces) == len(model["rooms"]),
      f"{len(spaces)} vs {len(model['rooms'])}")

# --- 6. a flat-topped model still writes ------------------------------------
flat = M.build([M.Room("s", 0, 0, 6, 4, 2.4)], storeys=1, storey_height=2.4)
p2 = os.path.join(td, "flat.ifc")
M.write_ifc(flat, p2)
f2 = ifcopenshell.open(p2)
check("6a no roof entity when there is no roof",
      len(f2.by_type("IfcRoof")) == 0)
check("6b but the slab and walls are still there",
      len(f2.by_type("IfcSlab")) == 1 and len(f2.by_type("IfcWall")) == 4)


print()
for x in FAILED:
    print(f"FAIL  {x}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
