#!/usr/bin/env python3
"""clay_locked.py — matched-pair CLAY renders at a LOCKED camera.

Written 2026-08-21 for the TripoSF / SparseFlex round-trip experiment, where the
question is "does the representation preserve sharpness" and the arbiter has to
be a render, not a number (CLAUDE.md: crease_density is a candidate finder, and
there is a recorded case of crease going 43 -> 132 on a melted blob).

WHY CLAY.  A round-trip through a geometry VAE returns geometry only — no
materials, no UVs.  Any comparison that shades the two meshes differently is not
a comparison.  So both sides get ONE identical neutral material and identical
lights, and the only thing that can differ between the two images is the shape.

RIG RULES, every one of them already paid for and recorded in CLAUDE.md:
  * CYCLES only.  There is no EGL in this container and EEVEE cannot initialise.
  * view transform **Standard**, never AgX — AgX has produced three false
    verdicts here, one of which clipped 42.58% of the car's pixels.
  * exposure is VERIFIED NUMERICALLY and the clipped fraction is printed, not
    eyeballed.
  * the script prints its OWN done marker.  Blender prints "Blender quit" even
    when the render died after it, so never grep for that.
  * frames are deleted before the run, so a crashed render cannot leave a stale
    image that reads as success.
  * the camera comes from a JSON the CALLER fixes once, so a before/after pair
    is genuinely locked rather than each file being framed on its own bbox.

CANONICALISATION.  The camera is NOT placed from an assumed axis convention
(CLAUDE.md records renders burned twice rediscovering an azimuth mapping).
After import the world bbox is measured and the object is rotated so that
length->X, width->Y, height->Z, using the measured ordering: longest extent is
the length, and of the remaining two the SMALLER is the height.  That holds for
every car and is checked rather than assumed — the ratios are printed.

Usage:
  clay_locked.py MESH OUTDIR TAG --cams cams.json [--res 900] [--samples 48]
    cams.json: [{"name":"f34","az":45,"el":14,"dist":1.9,"lens":70}, ...]
       az is degrees about +Z from +X; el is degrees above the horizon;
       dist is in units of the car's own LENGTH.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

BLENDER = os.environ.get("BLENDER_BIN", "/opt/blender-4.5.12-linux-x64/blender")

_SCRIPT = r'''
import bpy, sys, math, json, os
from mathutils import Vector, Matrix
argv = sys.argv[sys.argv.index("--")+1:]
MESH, OUTD, TAG, CAMS, RES, SAMPLES, DENOISE = argv[0], argv[1], argv[2], json.loads(argv[3]), int(argv[4]), int(argv[5]), argv[6] == "1"

bpy.ops.wm.read_factory_settings(use_empty=True)
ext = os.path.splitext(MESH)[1].lower()
if ext == ".obj":
    bpy.ops.wm.obj_import(filepath=MESH)
elif ext == ".ply":
    bpy.ops.wm.ply_import(filepath=MESH)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=MESH)
else:
    raise SystemExit("CLAY_REFUSED unsupported extension " + ext)

objs = [o for o in bpy.data.objects if o.type == "MESH"]
if not objs:
    raise SystemExit("CLAY_REFUSED no mesh imported")

# --- join into one object so a single transform canonicalises everything ------
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
if len(objs) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

def world_bb(o):
    vs = [o.matrix_world @ v.co for v in o.data.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    return lo, hi

lo, hi = world_bb(ob)
ext3 = [hi[i] - lo[i] for i in range(3)]
order = sorted(range(3), key=lambda i: -ext3[i])          # longest first
ax_len = order[0]
ax_hgt = order[2]                                          # smallest of the three
ax_wid = order[1]
print("CLAY_EXTENTS raw=%.4f,%.4f,%.4f  length_axis=%d width_axis=%d height_axis=%d"
      % (ext3[0], ext3[1], ext3[2], ax_len, ax_wid, ax_hgt))

# build the permutation length->X, width->Y, height->Z (determinant +1)
cols = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
cols[0][ax_len] = 1.0
cols[1][ax_wid] = 1.0
cols[2][ax_hgt] = 1.0
M = Matrix(cols)
if M.determinant() < 0:
    M = Matrix([cols[0], [-c for c in cols[1]], cols[2]])
ob.matrix_world = M.to_4x4() @ ob.matrix_world
bpy.context.view_layer.update()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
lo, hi = world_bb(ob)
L, W, H = (hi[i] - lo[i] for i in range(3))
ctr = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2))
print("CLAY_CANON L=%.4f W=%.4f H=%.4f centre=%.4f,%.4f,%.4f" % (L, W, H, ctr.x, ctr.y, ctr.z))

# --- ONE clay material on everything -----------------------------------------
for m in list(bpy.data.materials):
    bpy.data.materials.remove(m)
clay = bpy.data.materials.new("Clay")
clay.use_nodes = True
bsdf = clay.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.42, 0.42, 0.44, 1.0)
bsdf.inputs["Roughness"].default_value = 0.42
bsdf.inputs["Metallic"].default_value = 0.0
ob.data.materials.clear()
ob.data.materials.append(clay)
for p in ob.data.polygons:
    p.material_index = 0
ob.data.shade_smooth() if hasattr(ob.data, "shade_smooth") else None

# --- world + lights, sized to the car ----------------------------------------
w = bpy.data.worlds.new("W"); bpy.context.scene.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1.0)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0

def area(name, loc, rot, size, energy):
    d = bpy.data.lights.new(name, type="AREA"); d.size = size; d.energy = energy
    o = bpy.data.objects.new(name, d); bpy.context.collection.objects.link(o)
    o.location = loc; o.rotation_euler = rot
    return o

# Energies scale with L^2 so a unit-normalised car and a 4 m car light the same.
# The absolute level is CALIBRATED, not guessed: the first attempt at 900*E
# clipped 36-42% of the frame, which is the exact AgX-class failure CLAUDE.md
# records.  LIGHT_SCALE is swept by the caller until mean sRGB lands near the
# 0.22 world background's ~130 and clipped_frac is ~0.
E = L * L * float(os.environ.get("CLAY_LIGHT_SCALE", "1.0"))
area("key",  (ctr.x + 1.1 * L, ctr.y - 1.0 * L, ctr.z + 1.3 * L), (math.radians(48), 0, math.radians(132)), 1.2 * L, 34 * E)
area("fill", (ctr.x - 1.2 * L, ctr.y + 1.1 * L, ctr.z + 0.9 * L), (math.radians(55), 0, math.radians(-48)), 1.6 * L, 13 * E)
area("rim",  (ctr.x - 0.2 * L, ctr.y - 1.4 * L, ctr.z + 0.6 * L), (math.radians(75), 0, math.radians(200)), 1.0 * L, 10 * E)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = DENOISE
sc.render.resolution_x = RES
sc.render.resolution_y = RES
sc.render.film_transparent = False
sc.view_settings.view_transform = "Standard"     # NEVER AgX
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.render.image_settings.file_format = "PNG"

cam_d = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cam_d)
bpy.context.collection.objects.link(cam); sc.camera = cam

os.makedirs(OUTD, exist_ok=True)
for c in CAMS:
    az = math.radians(c["az"]); el = math.radians(c["el"])
    dist = c["dist"] * L
    tgt = Vector((ctr.x + c.get("tx", 0.0) * L,
                  ctr.y + c.get("ty", 0.0) * L,
                  ctr.z + c.get("tz", 0.0) * H))
    cam.location = tgt + Vector((dist * math.cos(el) * math.cos(az),
                                 dist * math.cos(el) * math.sin(az),
                                 dist * math.sin(el)))
    d = tgt - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam_d.lens = c.get("lens", 70.0)
    p = os.path.join(OUTD, "%s_%s.png" % (TAG, c["name"]))
    if os.path.exists(p):
        os.remove(p)
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    # numeric exposure check — never eyeball it
    im = bpy.data.images.load(p)
    px = list(im.pixels)
    rgb = px[0::4] + px[1::4] + px[2::4]
    n = len(rgb)
    clipped = sum(1 for v in rgb if v >= 0.999) / n
    mean = sum(rgb) / n
    print("CLAY_FRAME %s mean_linear=%.4f mean_sRGB255=%.1f clipped_frac=%.5f"
          % (c["name"], mean, 255.0 * (mean ** (1 / 2.2)), clipped))
    bpy.data.images.remove(im)

print("CLAY_DONE %s" % TAG)
'''


def render(mesh, outdir, tag, cams, res=900, samples=48, denoise=True):
    os.makedirs(outdir, exist_ok=True)
    sp = os.path.join(outdir, "_clay_locked.py")
    with open(sp, "w") as f:
        f.write(_SCRIPT)
    cmd = [BLENDER, "-b", "-noaudio", "-P", sp, "--",
           mesh, outdir, tag, json.dumps(cams), str(res), str(samples),
           "1" if denoise else "0"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    keep = [l for l in out.splitlines()
            if l.startswith(("CLAY_", "Error", "Traceback")) or "Error:" in l]
    ok = any(l.startswith("CLAY_DONE") for l in out.splitlines())
    return ok, "\n".join(keep)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh")
    ap.add_argument("outdir")
    ap.add_argument("tag")
    ap.add_argument("--cams", required=True, help="path to cams JSON or inline JSON")
    ap.add_argument("--res", type=int, default=900)
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--no-denoise", action="store_true")
    a = ap.parse_args()
    cams = json.load(open(a.cams)) if os.path.exists(a.cams) else json.loads(a.cams)
    ok, log = render(a.mesh, a.outdir, a.tag, cams, a.res, a.samples, not a.no_denoise)
    print(log)
    if not ok:
        sys.exit("CLAY_FAILED — no CLAY_DONE marker")
