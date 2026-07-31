"""Strip baked-in environment geometry from a sourced GLB before it is rendered.

Some Sketchfab authors ship the car inside their own lighting rig. The 2025
Porsche Taycan Turbo GT and 2021 Toyota GR Yaris (same author series) both
contain an 80-face `Icosphere` at extent 1.9 x 2.0 x 2.0 while every car mesh is
about 0.02 x 0.05 x 0.01 - the backdrop is roughly 40x the car.

Left in place this wrecks three things at once, none of which look like the same
bug from the render:
  * FRAMING - the worker fits the camera to the whole scene, so the car becomes a
    speck and the studio floor ends up a mile beneath it (no ground reflection).
  * BODY DETECTION - the sphere's material is huge by area, so _choose_body()
    counts it as bodywork. The Taycan reported 67.7% "body" coverage across five
    materials; a respray would have flooded the backdrop, not the car.
  * SPEED - most camera rays hit the inside of a giant sphere and terminate, so
    the render finishes fast and looks flat, which reads as "cheap model" rather
    than "wrong scene".

Detection is a SIZE OUTLIER test, not a name test: `Icosphere` is this author's
name for it, the next author will call it something else. A mesh is environment
if it is much larger than the median mesh AND cheap enough to be a primitive.
Both conditions are required - a real car has large low-poly parts (a flat
windscreen) and small dense ones, but neither is 5x the median extent while
costing under a thousand faces.

Usage:  strip_env.py in.glb out.glb
"""
import os
import sys

# A backdrop primitive is BOTH an extreme size outlier and geometrically trivial.
SIZE_RATIO = 5.0     # x median mesh extent
MAX_FACES = 1000     # a sphere/box/plane rig; real car parts exceed this


def _bounds(o, mathutils):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for i in range(3):
            lo[i] = min(lo[i], w[i])
            hi[i] = max(hi[i], w[i])
    return [hi[i] - lo[i] for i in range(3)]


def strip(bpy, src, dst):
    """Import src, delete environment meshes, export dst. Returns a report."""
    import mathutils
    import statistics
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if len(meshes) < 3:
        # Too few meshes to have a reliable median; a fused shell has nothing to
        # strip anyway. Leave it completely alone rather than guess.
        return {"stripped": [], "kept": len(meshes), "reason": "too-few-meshes"}

    info = [(o, max(_bounds(o, mathutils)), len(o.data.polygons)) for o in meshes]
    med = statistics.median([m for _, m, _ in info]) or 1e-9
    env = [(o, m, f) for o, m, f in info if m > SIZE_RATIO * med and f <= MAX_FACES]
    if len(env) >= len(meshes):
        return {"stripped": [], "kept": len(meshes), "reason": "would-strip-everything"}

    drop = {id(o) for o, _, _ in env}
    names = [{"name": o.name, "extent": round(m, 3), "faces": f,
              "x_median": round(m / med, 1)} for o, m, f in env]
    if not names:
        return {"stripped": [], "kept": len(meshes), "reason": "none-found"}

    # Export the KEEPERS by selection. Deleting the objects and exporting the
    # whole scene does NOT work: bpy.data.objects.remove() empties the scene
    # correctly (verified: 44 meshes -> 43, name gone from bpy.data.objects) but
    # Blender 5.0's glTF exporter still writes all 44 back out. Selection-based
    # export is the only form that actually honours the removal.
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and id(o) not in drop:
            o.select_set(True)
            bpy.context.view_layer.objects.active = o
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True,
                              export_apply=True, export_yup=True,
                              export_materials="EXPORT")

    # Prove it. A strip that silently no-ops is worse than no strip at all: the
    # caller renders a car it believes is clean and the defect gets blamed on the
    # model. Re-import the file we just wrote and confirm the geometry is gone.
    stripped_names = {n["name"] for n in names}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=dst)
    back = [o.name for o in bpy.context.scene.objects if o.type == "MESH"]
    leaked = [n for n in back if n.split(".")[0] in {s.split(".")[0] for s in stripped_names}]
    return {"stripped": names, "kept": len(meshes) - len(names),
            "median_extent": round(med, 4), "verified_mesh_count": len(back),
            "leaked": leaked, "ok": not leaked and len(back) == len(meshes) - len(names)}


if __name__ == "__main__":
    import types
    sys.modules.setdefault("runpod", types.ModuleType("runpod"))
    import bpy
    src, dst = sys.argv[1], sys.argv[2]
    rep = strip(bpy, src, dst)
    print(rep)
    if rep["stripped"] and os.path.exists(dst):
        print(f"{os.path.getsize(src)/1e6:.1f}MB -> {os.path.getsize(dst)/1e6:.1f}MB")
