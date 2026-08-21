#!/usr/bin/env python3
"""sharp_views.py — render a GLB at NAMED, LOCKED cameras for the sharpness legs.

Written 2026-08-21 for the three-model sharpness experiment (TripoSF / Hunyuan3D-Omni /
Direct3D-S2). Two jobs, and they must be the SAME rig or the legs are not comparable:

  1. produce the RGBA CONDITIONING CUTOUT that an image-to-3D generator is fed, and
  2. produce the LOCKED "door" view in which a shut line is either visible or is not.

The gate limb "a visible door shut line at a locked camera" is only meaningful if the
input and the output are photographed by the same camera, so the camera set lives in
data (cams.json), not in prose.

CAMERA CONVENTION, stated because this project has burned renders twice rediscovering
an azimuth mapping (CLAUDE.md: "the render rig's azimuth convention"):
    az, el   DEGREES. az orbits the Blender +Z axis; el is the elevation angle.
    dist     multiplier on the mesh's bounding-box DIAGONAL.
    lens     millimetres. Long lenses flatten perspective; a car photographed at 115mm
             from far away is close to orthographic, which is what makes a shut line
             read as a line rather than a smear.
    tx, tz   aim-point offsets, as fractions of the diagonal, applied in the camera's
             own right/up axes so "nudge the framing left" means the same thing at any
             azimuth. Without this, tx would rotate with az and the framing would move.

RIG RULES that are not negotiable here, each one paid for:
  * STANDARD view transform, never AgX. AgX has produced three false verdicts in this
    project, including tiles that clipped 42.58% of car pixels.
  * CYCLES only (no EGL in this container, so EEVEE cannot run).
  * Denoising is attempted and the branch taken is PRINTED. A silent fallback looks
    identical to a successful upgrade in the output frames — the exact reason
    eyeball_views.py kept rendering undenoised for weeks after the 4.5.12 upgrade.
  * film_transparent, RGBA out: the cutout an image-to-3D pipeline wants, and it also
    lets the clipping measurement ignore the background instead of averaging it in.

CLIPPING IS REPORTED, NOT ASSUMED. --measure prints the fraction of *car* pixels at or
above 250/255 per channel. Judge exposure from that number before judging the car.

Draco: trimesh and Blender's importer both mis-read Draco-compressed GLBs (this repo has
a recorded case of an all-zero vertex array read as real geometry), so a Draco file must
be decompressed with `gltf-transform copy` before it reaches here. --check-draco refuses
rather than rendering something meaningless.

Usage:
  sharp_views.py MESH.glb OUTDIR [--cams cams.json] [--only door,cond] [--res 1024]
  sharp_views.py --measure OUTDIR/door.png
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

# Defaults are the sharptest set. `door` is the locked shut-line camera published by
# leg A in car-meshes/staging/sharptest/CHECKPOINT.md; `cond` is the 3/4 conditioning
# view fed to an image-to-3D generator.
DEFAULT_CAMS = {
    "door": {"az": 62, "el": 5, "dist": 1.15, "lens": 115, "tx": 0.06, "tz": -0.02},
    "cond": {"az": 35, "el": 12, "dist": 2.10, "lens": 85, "tx": 0.0, "tz": 0.0},
    "side": {"az": 0, "el": 4, "dist": 2.10, "lens": 85, "tx": 0.0, "tz": 0.0},
    "front": {"az": 90, "el": 6, "dist": 2.10, "lens": 85, "tx": 0.0, "tz": 0.0},
}

BLENDER_SCRIPT = r'''
import bpy, math, mathutils, os, sys, json
argv = sys.argv[sys.argv.index("--") + 1:]
MESH, OUTD, CAMS_JSON, RES, SAMPLES = argv[0], argv[1], argv[2], int(argv[3]), int(argv[4])
CAMS = json.loads(CAMS_JSON)

CLAY = os.environ.get("SHARP_CLAY", "0") == "1"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=MESH)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not objs:
    print("SHARP_VIEWS_FAIL: no mesh objects imported"); sys.exit(3)

# CLAY: one neutral matte material over everything. Two reasons, both load-bearing.
# (1) A generator that emits geometry only has no texture, so comparing its grey mesh
#     against a black gloss source would compare paint, not panels.
# (2) Black gloss actively HIDES creases -- the thing being counted. Clay is the
#     production brief's own required diagnostic pass for exactly this reason.
if CLAY:
    m = bpy.data.materials.new("clay"); m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.62, 0.62, 0.62, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.55
    for key in ("Metallic", "Specular IOR Level", "Coat Weight", "Transmission Weight"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(m)
    print("SHARP_VIEWS_CLAY: ON (all materials replaced with neutral matte)")

lo = mathutils.Vector((1e18,) * 3); hi = mathutils.Vector((-1e18,) * 3)
nverts = 0
for o in objs:
    nverts += len(o.data.vertices)
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for i in range(3):
            lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
ctr = (lo + hi) / 2
diag = (hi - lo).length
print(f"SHARP_VIEWS: objs={len(objs)} verts={nverts} diag={diag:.4f} "
      f"ext=({hi[0]-lo[0]:.3f},{hi[1]-lo[1]:.3f},{hi[2]-lo[2]:.3f})")
if diag <= 0 or nverts == 0:
    print("SHARP_VIEWS_FAIL: degenerate bounds"); sys.exit(3)

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"          # no EGL/GPU compute in this container
sc.cycles.samples = SAMPLES
# STANDARD, never AgX. Three false verdicts in this project came from AgX.
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0

# Denoise, and PRINT the branch. A silent fallback is indistinguishable from success.
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.view_layers[0].cycles.use_denoising = True
    print("SHARP_VIEWS_DENOISE: ON (OpenImageDenoise)")
except Exception as e:
    sc.cycles.use_denoising = False
    sc.view_layers[0].cycles.use_denoising = False
    print(f"SHARP_VIEWS_DENOISE: OFF -- {type(e).__name__}: {e}")

sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.render.resolution_x = RES
sc.render.resolution_y = RES
sc.render.resolution_percentage = 100

# Neutral three-point lighting. Deliberately soft and NOT a studio clearcoat rig: a
# blown specular highlight on a smooth panel hides the very crease we are counting,
# and this project has twice "fixed" a highlight that was never a defect.
world = bpy.data.worlds.new("W"); sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

def lamp(name, energy, rot, ang):
    d = bpy.data.lights.new(name, type="SUN"); d.energy = energy; d.angle = math.radians(ang)
    o = bpy.data.objects.new(name, d); sc.collection.objects.link(o)
    o.rotation_euler = rot; return o
lamp("key",  3.0, (math.radians(52), 0, math.radians(40)), 10)
lamp("fill", 1.2, (math.radians(62), 0, math.radians(215)), 25)
lamp("rim",  1.6, (math.radians(28), 0, math.radians(140)), 15)

cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam); sc.camera = cam

os.makedirs(OUTD, exist_ok=True)
for name, c in CAMS.items():
    az = math.radians(c["az"]); el = math.radians(c["el"])
    d = c["dist"] * diag
    loc = ctr + mathutils.Vector((d * math.cos(az) * math.cos(el),
                                  d * math.sin(az) * math.cos(el),
                                  d * math.sin(el)))
    cam.location = loc
    cam_d.lens = c.get("lens", 85)
    fwd = (ctr - loc).normalized()
    cam.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
    # tx/tz act in the CAMERA's own right/up axes so the nudge means the same thing at
    # every azimuth. Applied by moving the camera, which keeps the view direction.
    right = fwd.cross(mathutils.Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    cam.location = loc - right * (c.get("tx", 0.0) * diag) - up * (c.get("tz", 0.0) * diag)
    sc.render.filepath = os.path.join(OUTD, name + ".png")
    bpy.ops.render.render(write_still=True)
    print(f"SHARP_VIEWS_WROTE: {name}")
print("SHARP_VIEWS_DONE")
'''


def is_draco(path):
    try:
        with open(path, "rb") as fh:
            blob = fh.read(4_000_000)
        return b"KHR_draco_mesh_compression" in blob
    except Exception:
        return False


def measure(png):
    """Fraction of CAR pixels clipped, plus the car's mean level. Background excluded
    via the alpha channel, so a dark backdrop cannot flatter the exposure."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(png).convert("RGBA")).astype(np.float32)
    alpha = a[..., 3] > 8
    n = int(alpha.sum())
    if n == 0:
        print(f"{os.path.basename(png)}: NO CAR PIXELS (alpha empty)")
        return
    rgb = a[..., :3][alpha]
    clipped = float((rgb >= 250).any(axis=-1).mean())
    print(f"{os.path.basename(png)}: car_px={n} ({100.0*n/alpha.size:.1f}% of frame) "
          f"mean_sRGB={rgb.mean():.1f} p99={np.percentile(rgb,99):.1f} "
          f"clipped>=250: {100.0*clipped:.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh", nargs="?")
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--cams")
    ap.add_argument("--only")
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--measure", nargs="+")
    a = ap.parse_args()

    if a.measure:
        for p in a.measure:
            measure(p)
        return 0

    if not a.mesh or not a.outdir:
        ap.error("mesh and outdir required")
    if is_draco(a.mesh):
        raise SystemExit(
            f"REFUSED: {a.mesh} is Draco-compressed. Blender/trimesh mis-read Draco "
            f"here (a recorded all-zero vertex array read as real geometry). Run "
            f"`gltf-transform copy in.glb out.glb` first.")

    cams = dict(DEFAULT_CAMS)
    if a.cams and os.path.exists(a.cams):
        loaded = json.load(open(a.cams))
        cams.update(loaded if isinstance(loaded, dict) else {})
        print(f"cams.json merged: {sorted(loaded)}")
    if a.only:
        want = [s.strip() for s in a.only.split(",")]
        missing = [w for w in want if w not in cams]
        if missing:
            raise SystemExit(f"unknown camera(s): {missing}; have {sorted(cams)}")
        cams = {k: cams[k] for k in want}

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(BLENDER_SCRIPT)
        script = fh.name
    blender = os.environ.get("BLENDER_BIN", "blender")
    cmd = [blender, "-b", "--python", script, "--",
           os.path.abspath(a.mesh), os.path.abspath(a.outdir),
           json.dumps(cams), str(a.res), str(a.samples)]
    print("+", " ".join(cmd[:4]), "...")
    out = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(script)
    tail = out.stdout.strip().splitlines()
    for ln in tail:
        if ln.startswith("SHARP_VIEWS") or "Error" in ln or "Traceback" in ln:
            print(" ", ln)
    # Blender prints "Blender quit" even when the render died, so the script's OWN
    # marker is the only trustworthy success signal (recorded trap).
    if "SHARP_VIEWS_DONE" not in out.stdout:
        print(out.stdout[-3000:]); print(out.stderr[-2000:])
        raise SystemExit("SHARP_VIEWS did not reach its DONE marker")
    for name in cams:
        p = os.path.join(a.outdir, name + ".png")
        if os.path.exists(p):
            measure(p)
        else:
            print(f"  MISSING {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
