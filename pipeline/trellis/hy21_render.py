"""hy21_render.py — our own Blender stage for Hunyuan3D-2.1 training data.

REPLACES `tools/render/render.py` from the Hunyuan repo. That script is a
TRELLIS derivative carrying dependencies and assumptions this project has
already been burned by:

  * `cycles.use_denoising = True` — hard-crashes on any Blender built without
    OpenImageDenoiser (our container's distro build). Denoising is meaningless
    for the geometry pass anyway.
  * imports `cv2` at module scope INTO BLENDER'S PYTHON, plus OpenEXR/Imath, so
    the render stage cannot start until three packages are installed into an
    interpreter we do not otherwise use.
  * fixing either by `sed` on a vendored file is the documented trap that once
    silently rewrote a URL and cost eight pod runs. Owning the file is cheaper.

WHAT THE TRAINER ACTUALLY NEEDS — read from `hy3dshape/data/dit_asl.py`, not
from the README, because they disagree. `decode()` reads exactly:

    render_cond/{000..023}.png     RGBA, alpha IS the mask (it asserts
                                   `image.shape[2] == 4`)
    geo_data/{uid}_surface.npz     random_surface + sharp_surface

and `transforms.json`, `_sdf.npz` and `_watertight.obj` are all COMMENTED OUT
for DiT fine-tuning — they belong to VAE training. So this stage emits the 24
RGBA views plus `mesh.ply`; the surface npz is produced from that ply by their
own `watertight_and_sample.py`, which is kept deliberately: it is the
numerically-sensitive half (watertight inflation, sharp-edge sampling, float16
layout) and matching it exactly matters more than owning it.

NORMALISATION is matched to their reference data: `mesh.ply` in the shipped
mini_trainset is centred with its LONGEST axis spanning exactly 1.0, i.e.
vertices in [-0.5, 0.5], aspect preserved. Verified against all three sample
cases before this was written.

UPGRADES over the script it replaces:
  * runs on any Blender build (no OIDN, no cv2/OpenEXR in Blender's python)
  * true RGBA with film_transparent, so alpha is a real mask, not a chroma key
  * deterministic Fibonacci-sphere camera orbit — even view coverage instead of
    a random azimuth ring, so 24 views actually see the roof and underside
  * Draco-compressed inputs are rejected loudly rather than silently rendering
    an empty frame (trimesh/Blender return placeholder zeros for them)
  * asserts the object is non-degenerate and that every expected file was
    written, so a silent no-output run cannot read as success

Usage (inside Blender):
  xvfb-run -a blender -b --factory-startup -noaudio -P hy21_render.py -- \
      --object car.glb --output_folder OUT/render_cond [--views 24]
      [--resolution 512] [--samples 16]
"""
import argparse
import json
import math
import os
import sys

import bpy
import mathutils


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", required=True)
    ap.add_argument("--output_folder", required=True)
    ap.add_argument("--views", type=int, default=24)
    ap.add_argument("--resolution", type=int, default=512)
    ap.add_argument("--samples", type=int, default=16)
    return ap.parse_args(argv)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def check_not_draco(path):
    """Draco positions decode to nothing in some importers; fail loudly."""
    if not path.lower().endswith(".glb"):
        return
    import struct
    with open(path, "rb") as f:
        head = f.read(1 << 20)
    if head[:4] != b"glTF":
        return
    ln = struct.unpack("<I", head[12:16])[0]
    try:
        js = json.loads(head[20:20 + min(ln, len(head) - 20)])
    except Exception:
        return
    ext = set(js.get("extensionsUsed", [])) | set(js.get("extensionsRequired", []))
    if "KHR_draco_mesh_compression" in ext:
        raise SystemExit("FATAL: input is Draco-compressed; decompress first "
                         "(gltf-transform copy in.glb out.glb)")


def import_object(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise SystemExit(f"FATAL: unsupported input extension {ext}")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("FATAL: no mesh objects after import")
    return meshes


def normalise(meshes):
    """Centre and scale so the LONGEST axis spans exactly 1.0 → verts in [-.5,.5].

    Matches the `mesh.ply` convention in Hunyuan's own mini_trainset (measured:
    longest-axis extent 1.000, bbox symmetric about the origin, aspect kept).
    """
    lo = mathutils.Vector((1e30,) * 3)
    hi = mathutils.Vector((-1e30,) * 3)
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
    ext = hi - lo
    longest = max(ext)
    if longest <= 1e-9:
        raise SystemExit("FATAL: degenerate object (zero extent)")
    ctr = (lo + hi) / 2.0
    s = 1.0 / longest

    # Apply the transform DIRECTLY to each object's world matrix. Re-parenting
    # to an empty and scaling the parent looked equivalent and was not: the PLY
    # export came out at 0.0466 instead of 1.0 and every render was empty
    # (alpha coverage 0.000). Caught by the format test, not by reading the code.
    T = (mathutils.Matrix.Translation(-ctr * s)
         @ mathutils.Matrix.Diagonal((s, s, s, 1.0)))
    # Transform every SCENE ROOT, whatever its type. Filtering `meshes` by
    # `parent is None` transformed NOTHING on a real car: the glTF importer
    # parents meshes under node empties, so no mesh is its own root. That is
    # how the first version produced a 0.0466-scale ply and 24 empty frames.
    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    if not roots:
        raise SystemExit("FATAL: no scene roots to transform")
    for o in roots:
        o.matrix_world = T @ o.matrix_world
    bpy.context.view_layer.update()

    # VERIFY the transform actually landed — never trust it silently.
    lo2 = mathutils.Vector((1e30,) * 3); hi2 = mathutils.Vector((-1e30,) * 3)
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo2[i] = min(lo2[i], w[i]); hi2[i] = max(hi2[i], w[i])
    ext2 = hi2 - lo2
    got = max(ext2)
    if not (0.99 <= got <= 1.01):
        raise SystemExit(f"FATAL: normalisation failed — longest axis {got:.4f}, expected 1.0")
    if max(abs(v) for v in (lo2 + hi2) / 2.0) > 0.01:
        raise SystemExit(f"FATAL: not centred — centre {[round(v,4) for v in (lo2+hi2)/2.0]}")
    return longest, ctr


def fibonacci_views(n, radius):
    """Even coverage of the sphere — beats a fixed azimuth ring.

    A ring at one elevation never sees the roof or the underside; the DiT is
    conditioned on ONE randomly chosen view per sample, so every view has to be
    a plausible, informative look at the car.
    """
    pts = []
    ga = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        # bias away from the exact poles: nothing useful is straight down
        y = 1.0 - (i + 0.5) / n * 2.0
        y *= 0.82
        r = math.sqrt(max(0.0, 1.0 - y * y))
        th = ga * i
        pts.append(mathutils.Vector((math.cos(th) * r, y, math.sin(th) * r)) * radius)
    return pts


def look_at(cam, loc, target=mathutils.Vector((0, 0, 0))):
    d = (loc - target)
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    cam.matrix_world = mathutils.Matrix.Translation(loc) @ rot


def setup_scene(res, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    # No OIDN in many builds, and denoising is pointless for a geometry pass.
    sc.cycles.use_denoising = False
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"   # the loader ASSERTS 4 channels
    sc.render.film_transparent = True              # alpha = a true mask
    sc.view_settings.view_transform = "Standard"   # AgX once clipped a tyre white
    sc.view_settings.look = "None"

    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    cam_d = bpy.data.cameras.new("C")
    cam_d.type = "PERSP"
    cam_d.lens = 40
    cam = bpy.data.objects.new("C", cam_d)
    bpy.context.collection.objects.link(cam)
    sc.camera = cam

    # three-point rig, keyed off the unit-cube scale so exposure is stable
    for loc, e in (((2.2, -2.2, 2.0), 320.0),
                   ((-2.4, 1.6, 1.4), 180.0),
                   ((0.4, 2.6, -1.2), 90.0)):
        d = bpy.data.lights.new("L", type="AREA")
        d.energy = e
        d.size = 3.0
        ob = bpy.data.objects.new("L", d)
        ob.location = loc
        bpy.context.collection.objects.link(ob)
        t = ob.constraints.new("TRACK_TO")
        emp = bpy.data.objects.new("T", None)
        bpy.context.collection.objects.link(emp)
        t.target = emp
    return cam


def export_ply(path):
    for o in bpy.context.scene.objects:
        o.select_set(o.type == "MESH")
    bpy.ops.wm.ply_export(filepath=path, export_selected_objects=True,
                          apply_modifiers=True, export_normals=True,
                          export_uv=False, export_colors="NONE",
                          ascii_format=False)


def main():
    a = parse_args()
    os.makedirs(a.output_folder, exist_ok=True)
    check_not_draco(a.object)
    reset()
    meshes = import_object(a.object)
    longest, ctr = normalise(meshes)
    print(f"HY21 normalise: longest_axis={longest:.4f} centre={[round(v,4) for v in ctr]}")

    cam = setup_scene(a.resolution, a.samples)
    cams = fibonacci_views(a.views, radius=1.9)

    # Per-view framing. A car is long and thin, so a fixed camera radius wastes
    # most of the frame on background: measured 8.8% alpha coverage against
    # Hunyuan's own 21.2%. The DiT trains on a CROP of this image, so wasted
    # frame is wasted resolution on the exact panel detail we are trying to
    # teach. `camera_fit_coords` slides the camera along its view axis until the
    # supplied points just fit, which is per-view-exact rather than a
    # bounding-sphere approximation.
    corners = []
    for o in [x for x in bpy.context.scene.objects if x.type == "MESH"]:
        for c in o.bound_box:
            corners.append(o.matrix_world @ mathutils.Vector(c))
    flat = [v for c in corners for v in c]
    dg = bpy.context.evaluated_depsgraph_get()
    MARGIN = 1.06          # a little air so the crop never clips a wing mirror

    frames = []
    for i, loc in enumerate(cams):
        look_at(cam, loc)
        bpy.context.view_layer.update()
        fit_loc, _ = cam.camera_fit_coords(dg, flat)
        cam.location = mathutils.Vector(fit_loc) * MARGIN
        bpy.context.view_layer.update()
        out = os.path.join(a.output_folder, f"{i:03d}.png")
        bpy.context.scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        frames.append({"file_path": f"{i:03d}.png",
                       "transform_matrix": [list(r) for r in cam.matrix_world]})
        print(f"  view {i:03d} -> {out}", flush=True)

    # transforms.json is unused by the DiT dataloader (commented out there) but
    # is cheap, and the VAE path and any future pose conditioning want it.
    with open(os.path.join(a.output_folder, "transforms.json"), "w") as f:
        json.dump({"camera_angle_x": bpy.data.cameras[0].angle_x,
                   "normalisation": {"longest_axis": longest,
                                     "centre": [ctr.x, ctr.y, ctr.z],
                                     "convention": "verts in [-0.5,0.5], longest axis = 1.0"},
                   "frames": frames}, f, indent=1)

    ply = os.path.join(a.output_folder, "mesh.ply")
    export_ply(ply)

    # ARTEFACT assertions — a silent no-output run must never read as success.
    missing = [f"{i:03d}.png" for i in range(a.views)
               if not os.path.exists(os.path.join(a.output_folder, f"{i:03d}.png"))]
    if missing:
        raise SystemExit(f"FATAL: missing renders {missing[:5]}")
    if not os.path.exists(ply) or os.path.getsize(ply) < 1000:
        raise SystemExit("FATAL: mesh.ply not written")
    print(f"HY21_RENDER_OK views={a.views} ply={os.path.getsize(ply)}")


if __name__ == "__main__":
    main()
