"""Tests for the Cycles renderer — the contract, not the pixels.

Blender is a 370MB optional dependency that may not be installed at all, so
almost everything here is about the BOUNDARY: that we never import bpy into
the worker, that a missing Blender degrades instead of failing a job, and
that the tuned lighting constants stay in the relationship that made the
render legible. The one live render runs only where bpy actually exists.

Run: python building/test_blend.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import blend as B  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


# --- 1. the licence boundary ------------------------------------------------
# Blender is GPL. Importing bpy into the worker would link our code to it;
# running it as a separate program does not. This is the whole reason the
# module is shaped the way it is, so it is asserted rather than trusted.
src = open(os.path.join(HERE, "blend.py")).read()
top = [l for l in src.splitlines()
       if l.startswith("import ") or l.startswith("from ")]
check("1a the worker never imports bpy at module level",
      not any("bpy" in l for l in top), str(top))
# Asked of the PARSED module, not of the text. A grep also matches the
# docstring sentence explaining why we never import bpy, which is prose, not
# an import — the AST knows the difference and the string search does not.
import ast  # noqa: E402
tree = ast.parse(src)
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split(".")[0])
check("1b bpy is never imported anywhere in the module's own code",
      "bpy" not in imported, str(sorted(imported)))
check("1c it goes through subprocess", "subprocess.run" in src)
check("1d and the licence reason is written down",
      "GPL" in src and "derivative" in src)


# --- 2. degrading instead of failing ----------------------------------------
ok, why = B.available("/nonexistent/python")
check("2a a missing interpreter is reported, not raised", ok is False)
check("2b with a reason", isinstance(why, str) and len(why) > 10, why)

try:
    B.render("/no/such/model.glb", "/tmp/x.png")
    check("2c a missing model is refused", False)
except B.BlendError as e:
    check("2c a missing model is refused", "no such model" in str(e), str(e))

# views() must never let one failed angle take the others, or the job, down.
with tempfile.TemporaryDirectory() as td:
    got = B.views("/no/such/model.glb", td, "x", python="/nonexistent/python")
    check("2d a failed view returns nothing rather than raising", got == [],
          str(got))


# --- 3. the tuned lighting stays in relationship ----------------------------
# These were arrived at by sweeping three tone mappings; each one alone is
# meaningless and the combination is what makes brick look like brick.
check("3a the exposure is pulled well down", B.EXPOSURE <= -1.5,
      str(B.EXPOSURE))
check("3b the sky is fill, not key", B.SKY_STRENGTH < 0.5,
      str(B.SKY_STRENGTH))
check("3c the sun does the keying", B.SUN_ENERGY >= 2.0, str(B.SUN_ENERGY))
check("3d brick is a low linear albedo, not an sRGB pick",
      B._MATERIALS["brick"]["base"][0] < 0.45, str(B._MATERIALS["brick"]))
check("3e brick is actually red", B._MATERIALS["brick"]["base"][0]
      > B._MATERIALS["brick"]["base"][1] * 2.5)
check("3f roof tile is near black", B._MATERIALS["tile"]["base"][0] < 0.10)
check("3g glass transmits", B._MATERIALS["glass"].get("transmission", 0) > 0.5)
check("3h every material model3d exports has a Cycles counterpart",
      all(m in B._MATERIALS for m in
          ("brick", "plaster", "tile", "glass", "door", "slab", "floor")))


# --- 4. the backdrop is composited, not rendered ----------------------------
check("4a the film is transparent", "film_transparent = True" in src)
check("4b and a sky is dropped in afterwards", "_drop_in_sky" in src)
check("4c the reason is recorded",
      "crushes the sky" in src or "physically bright" in src)

try:
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.png")
        # A transparent frame with one opaque dark pixel block in it.
        im = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
        for x in range(10, 20):
            for y in range(10, 20):
                im.putpixel((x, y), (20, 20, 20, 255))
        im.save(p)
        B._drop_in_sky(p)
        out = Image.open(p).convert("RGB")
        check("4d the transparent area became sky",
              out.getpixel((2, 1))[2] > out.getpixel((2, 1))[0],
              str(out.getpixel((2, 1))))
        check("4e the sky is a gradient, not flat",
              out.getpixel((2, 1)) != out.getpixel((2, 28)),
              f"{out.getpixel((2,1))} {out.getpixel((2,28))}")
        check("4f the building survived compositing",
              sum(out.getpixel((15, 15))) < 120, str(out.getpixel((15, 15))))
except ImportError:
    print("note: PIL absent, skipping the compositing tests")


# --- 5. a real render, only where Blender exists ----------------------------
ok, ver = B.available()
if ok:
    check("5a bpy reports a version", ver[0].isdigit(), ver)
    glb = None
    for cand in ("fairway9b.glb", "final.glb"):
        for root in (tempfile.gettempdir(),
                     "/tmp/claude-0/-home-user-triposr-runpod-worker/"
                     "0d72ac03-79be-5ec7-9bc0-182a6c918c9f/scratchpad"):
            p = os.path.join(root, cand)
            if os.path.exists(p):
                glb = p
                break
        if glb:
            break
    if glb:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "r.png")
            B.render(glb, out, samples=8, width=200, height=150)
            from PIL import Image
            im = Image.open(out).convert("RGB")
            check("5b a render is produced", im.size == (200, 150),
                  str(im.size))
            cols = im.getcolors(200 * 150) or []
            check("5c it is not a blank frame", len(cols) > 20, str(len(cols)))
            # The whole failure this module fought: a washed-out white image.
            light = sum(n for n, c in cols if min(c) > 235)
            check("5d it is not blown out to white",
                  light < 200 * 150 * 0.5, f"{light} near-white pixels")
    else:
        print("note: no sample GLB to render")
else:
    print(f"note: Blender not installed here ({ver}) — skipping live render")


print()
for f in FAILED:
    print(f"FAIL  {f}")
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
