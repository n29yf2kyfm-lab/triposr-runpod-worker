"""Tests for the model preview, and for the four geometry bugs drawing it found.

Every bug covered here shipped green. The suite checked areas, counts and
lengths, and all of those were right while the model itself was wrong: brick
on the inside face, a 350mm band of daylight at every floor, a first floor on
top of a single-storey extension, and an extension left open to the sky.
Numbers cannot see any of that. A picture sees all four at a glance, which is
why preview.py exists — and why these assertions are about WHERE the surfaces
are, not how many square metres they add up to.

Run: python building/test_preview.py
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import model3d as M   # noqa: E402
import preview        # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def plan_xy(p):
    """glTF (x, y_up, z) back to plan (x, y). The exporter maps plan y to -z."""
    return (p[0], -p[2])


# --- 1. the brick goes on the OUTSIDE ---------------------------------------
# Room.corners() winds counter-clockwise, so the wall's left normal points
# INWARD. Every exporter that assumed +n was outside put the brickwork in the
# living room and the plaster on the street.
room = M.Room("single", 0.0, 0.0, 6.0, 4.0, 2.4)
model = M.build([room], storeys=1, storey_height=2.4)
groups = M._glb_mesh(model)
centre = (3.0, 2.0)


def mean_offset(mat):
    pos = groups[mat][0]
    pts = [plan_xy((pos[i], pos[i + 1], pos[i + 2]))
           for i in range(0, len(pos), 3)]
    return sum(max(abs(x - centre[0]) / 3.0, abs(y - centre[1]) / 2.0)
               for x, y in pts) / len(pts)


check("1a the model has brick and plaster faces",
      "brick" in groups and "plaster" in groups, str(sorted(groups)))
check("1b brick sits further out than plaster",
      mean_offset("brick") > mean_offset("plaster"),
      f"brick {mean_offset('brick'):.4f} plaster {mean_offset('plaster'):.4f}")
check("1c every wall knows which way is out",
      all(w["outward"] in (1, -1) for w in model["walls"]))


# --- 2. no band of daylight at floor level ----------------------------------
# Walls built at ceiling height while storeys stack at floor-to-floor leave a
# gap right round the building at every level.
tall = M.Room("two storey", 0.0, 0.0, 6.0, 4.0, 2.75)
stacked = M.build([tall], storeys=2, storey_height=2.75)
check("2a eaves sit on top of the walls, not a floor zone above them",
      abs(stacked["eaves_z_m"] - 5.5) < 1e-6, str(stacked["eaves_z_m"]))
zs = []
for mat, (pos, _, _) in M._glb_mesh(stacked).items():
    if mat in ("brick", "plaster"):
        zs += [pos[i + 1] for i in range(0, len(pos), 3)]
# With walls the full storey height there is no z the walls do not reach.
check("2b walls are continuous through the floor zone",
      any(abs(z - 2.75) < 1e-6 for z in zs) and max(zs) >= 5.5 - 1e-6,
      f"max {max(zs)}")


# --- 3. a single-storey block does not repeat up the building ---------------
house = M.Room("house", 0.0, 0.0, 8.0, 6.0, 2.75)
ext = M.Room("extension", 0.0, 6.0, 8.0, 3.0, 2.4, kind="extension",
             storeys=1)
both = M.build([house, ext], storeys=2, storey_height=2.75)

ext_walls = [w for w in both["walls"] if w.get("storeys") == 1]
check("3a the extension's walls are marked single storey", len(ext_walls) >= 2,
      str(len(ext_walls)))
check("3b _wall_on_level keeps them on the ground floor",
      M._wall_on_level(ext_walls[0], 0))
check("3c _wall_on_level drops them from the first floor",
      not M._wall_on_level(ext_walls[0], 1))
check("3d a wall with no storey limit is on every level",
      M._wall_on_level({"storeys": None}, 5))

# Nothing belonging to the extension may appear above its own head height.
groups2 = M._glb_mesh(both)
above = 0
for mat, (pos, _, _) in groups2.items():
    if mat not in ("brick", "plaster"):
        continue
    for i in range(0, len(pos), 3):
        x, y = plan_xy((pos[i], pos[i + 1], pos[i + 2]))
        if y > 6.05 and pos[i + 1] > 2.45:
            above += 1
check("3e no geometry stands above the single-storey extension", above == 0,
      f"{above} vertices")


# --- 4. the extension is not left open to the sky ---------------------------
caps = both.get("caps") or []
check("4a a cap was raised over the shallower block", len(caps) == 1,
      str(caps))
if caps:
    c = caps[0]
    check("4b the cap is at the extension's head height",
          abs(c["z_m"] - 2.4) < 1e-6, str(c["z_m"]))
    check("4c the cap covers the extension footprint",
          abs(c["x"][0] - 0.0) < 1e-6 and abs(c["x"][1] - 8.0) < 1e-6
          and abs(c["y"][0] - 6.0) < 1e-6 and abs(c["y"][1] - 9.0) < 1e-6,
          str(c))
check("4d a uniform building gets no caps",
      (M.build([house], storeys=2, storey_height=2.75).get("caps") or []) == [])
check("4e the cap is a roof surface in the export",
      any(abs(p - 2.4) < 1e-6
          for p in groups2["tile"][0][1::3]) if "tile" in groups2 else False)


# --- 5. internal low down, external higher up -------------------------------
# The wall between a two-storey house and a single-storey extension has a
# room both sides at ground level and open weather above the flat roof.
shared = [w for w in both["walls"] if w.get("shared_storeys") is not None]
check("5a the shared wall was found", len(shared) == 1, str(len(shared)))
if shared:
    check("5b shared only as far as the shallower block goes",
          shared[0]["shared_storeys"] == 1, str(shared[0]["shared_storeys"]))
# At first-floor level that wall must be brick, not bare plaster facing out.
brick_y = [plan_xy((groups2["brick"][0][i], groups2["brick"][0][i + 1],
                    groups2["brick"][0][i + 2]))[1]
           for i in range(0, len(groups2["brick"][0]), 3)
           if groups2["brick"][0][i + 1] > 2.8]
check("5c the elevation above the extension roof is brickwork",
      any(abs(y - 6.0) < 0.2 for y in brick_y),
      "no brick on the shared wall line above the extension")


# --- 6. the preview itself ---------------------------------------------------
check("6a horizontal plates are excluded from an outside view",
      "slab" not in preview.EXTERIOR_MATERIALS
      and "floor" not in preview.EXTERIOR_MATERIALS)
check("6b plasterwork is kept", "plaster" in preview.EXTERIOR_MATERIALS)

faces = preview._faces(both)
check("6c the preview draws the exported triangles", len(faces) > 50,
      str(len(faces)))
check("6d and none of the excluded ones",
      all(n in preview.EXTERIOR_MATERIALS for _, _, n in faces))

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

if HAVE_PIL:
    with tempfile.TemporaryDirectory() as td:
        p = preview.render(both, os.path.join(td, "v.png"), size=240)
        img = Image.open(p).convert("RGB")
        check("6e a picture is produced at the size asked for",
              img.size == (240, 240), str(img.size))
        cols = img.getcolors(240 * 240) or []
        check("6f it is not a blank page", len(cols) > 8, str(len(cols)))
        # The building has to actually be IN frame, not off the edge. The
        # backdrop is a sky gradient over grass now, so "anything not the
        # flat background colour" is the whole picture — the building is what
        # is neither sky (blue-dominant) nor ground (green-dominant).
        def is_sky(c):
            return c[2] > c[0] + 8 and c[2] > c[1] + 4

        def is_ground(c):
            return c[1] > c[0] + 8 and c[1] > c[2] + 8

        building = sum(n for n, c in cols
                       if not is_sky(c) and not is_ground(c))
        frac = building / float(240 * 240)
        check("6g the building fills a sensible part of the frame",
              0.15 < frac < 0.85, f"{frac:.2f}")
        check("6h there is sky above it",
              any(is_sky(img.getpixel((x, 4))) for x in range(0, 240, 8)))
        check("6i and ground below it",
              any(is_ground(img.getpixel((x, 236)))
                  for x in range(0, 240, 8)))

        # Three named views, and losing one must not lose the others.
        outs = preview.views(both, td, "t")
        check("6j a proposal ships more than one view", len(outs) == 3,
              str(len(outs)))
        check("6k the views are distinct files",
              len({os.path.basename(o[0]) for o in outs}) == 3)

    try:
        preview.render({"walls": [], "rooms": [], "storeys": 1,
                        "storey_height_m": 2.4,
                        "extent_m": {"x": [0, 1], "y": [0, 1]}},
                       os.path.join(tempfile.gettempdir(), "empty.png"))
        check("6l an empty model is refused, not drawn blank", False)
    except ValueError:
        check("6l an empty model is refused, not drawn blank", True)
else:
    print("note: PIL absent, skipping the drawing tests")


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
