"""proof_views.py — the EIGHT-VIEW proof render the production brief asks for.

Owner brief item 8, verbatim: "Neutral-grey studio and visible ground shadow.
Eight complete views: front, rear, both sides and four corners."

WHY THIS EXISTS ALONGSIDE eyeball_views.py. eyeball_views renders SEVEN
azimuths chosen so both ends are always visible on a mesh whose nose direction
is unknown — it is a diagnostic for an uncanonicalised car. This one is for a
car whose pose is already decided, so the eight views are NAMED (front, rear,
front-left, ...) and the naming is only honest once nose direction is fixed.
Run it on canonicalised output, never on a raw generator dump.

TWO THINGS THE BRIEF SINGLES OUT, both deliberate here:

  * NEUTRAL GREY, NOT BLACK. "Stop using the black background — it conceals
    defects." Correct, and it is not only a background issue: the studio rig's
    black backdrop also removes the bounce that makes a lower flank readable.
    World is 0.22 grey (the value CLAUDE.md calibrates exposure against: 0.22
    world must land near sRGB 130 under Standard view transform) and the floor
    is a slightly darker grey so the car does not float in a void.

  * A REAL GROUND SHADOW, from real geometry. A shadow-catcher plane is used
    rather than a fake contact blob, so the shadow reports the car's ACTUAL
    ground contact. That matters here: this project has shipped cars floating
    190mm in the air whose whole-model bbox test still said "on ground",
    because the test read the lowest vertex in the scene (a splitter) rather
    than the tyres. A visible cast shadow makes that failure obvious by eye.

Standard view transform, never AgX: AgX has twice clipped a tyre to pure white
in this project and inverted a material verdict.

Run: blender -b --python proof_views.py -- <car.glb> <outdir> [res] [samples]
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD = argv[0], argv[1]
RES = int(argv[2]) if len(argv) > 2 else 900
SAMPLES = int(argv[3]) if len(argv) > 3 else 48

if not os.path.exists(GLB):
    raise SystemExit(f"REFUSED: no such file: {GLB}")
with open(GLB, "rb") as f:
    if f.read(4) != b"glTF":
        raise SystemExit(f"REFUSED: {GLB} is not a GLB (bad magic)")
os.makedirs(OUTD, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("REFUSED: no mesh in the GLB")

# world bbox from evaluated geometry
lo = mathutils.Vector((1e9,) * 3)
hi = mathutils.Vector((-1e9,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        lo = mathutils.Vector((min(lo[i], w[i]) for i in range(3)))
        hi = mathutils.Vector((max(hi[i], w[i]) for i in range(3)))
ctr = (lo + hi) / 2
ext = hi - lo
diag = ext.length

# ---- neutral grey world (0.22) ------------------------------------------
world = bpy.data.worlds.new("w")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.22, 0.22, 0.22, 1.0)
bg.inputs[1].default_value = 1.0

# ---- floor as REAL geometry, so the shadow is an honest contact report ---
bpy.ops.mesh.primitive_plane_add(size=diag * 6, location=(ctr.x, ctr.y, lo.z))
floor = bpy.context.active_object
fm = bpy.data.materials.new("floor")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.16, 0.16, 0.17, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.65
floor.data.materials.append(fm)

# key + fill + rim, all casting so the contact shadow is real
for name, loc, energy, size in (
    ("key",  (diag * 1.4, -diag * 1.2, diag * 1.5), 6.0, diag * 0.8),
    ("fill", (-diag * 1.5, -diag * 0.9, diag * 0.9), 2.2, diag * 1.1),
    ("rim",  (0.0, diag * 1.7, diag * 1.1), 2.6, diag * 0.9),
):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy * diag * diag
    ld.size = size
    lo_ = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(lo_)
    lo_.location = (ctr.x + loc[0], ctr.y + loc[1], lo.z + loc[2])
    d = (ctr - mathutils.Vector(lo_.location))
    lo_.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
sc.cycles.device = "CPU"
# Denoise when the build supports it. PRINT which branch ran: a silent
# fallback is indistinguishable from a successful upgrade in the output.
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    print("PROOF_DENOISE: ON (OpenImageDenoise)")
except (TypeError, AttributeError) as e:
    sc.cycles.use_denoising = False
    print(f"PROOF_DENOISE: OFF ({type(e).__name__}: {e})")
sc.view_settings.view_transform = "Standard"      # never AgX
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.film_transparent = False

cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 85                                    # long lens: a wide lens makes
cam = bpy.data.objects.new("cam", cam_d)           # a symmetric car photograph
bpy.context.collection.objects.link(cam)           # asymmetric
sc.camera = cam

# The LENGTH axis decides which azimuth is "front". Named views are only
# honest on a canonicalised car — see the module docstring.
L = max(range(3), key=lambda i: ext[i])
VIEWS = [("front", 0), ("front_left", 45), ("left", 90), ("rear_left", 135),
         ("rear", 180), ("rear_right", 225), ("right", 270), ("front_right", 315)]
elev = math.radians(14)

# PER-VIEW FRAME FIT — a fixed radius CLIPPED THE CAR on its first outing.
# radius = 1.35 x diag framed the front/rear/corner views correctly and cut
# the nose AND tail off both PURE SIDE views: an 85mm lens is ~24 deg
# horizontal, and a 4.28m car side-on needs more standoff than its diagonal
# suggests. Caught by the reviewer council (the Fable 5 half, eyeballing the
# full-res frames) AFTER the sheet had been presented as "eight complete
# views" — neither scriptable reviewer flagged it from the downscaled sheet.
# So the fit is now computed per view from the projected bbox corners, and
# REFUSES to write a frame whose corners do not fit: a proof render that
# crops its subject is not a proof.
corners_w = [mathutils.Vector((x, y, z))
             for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]

def fit_radius(a_rad):
    from bpy_extras.object_utils import world_to_camera_view as w2cv
    r = diag * 1.35
    for _ in range(4):                       # converges in 2; 4 is margin
        off = mathutils.Vector((math.cos(a_rad) * r * math.cos(elev),
                                math.sin(a_rad) * r * math.cos(elev),
                                r * math.sin(elev)))
        if L == 1:
            off = mathutils.Vector((off.y, off.x, off.z))
        cam.location = ctr + off
        cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        dev = max(max(abs(p.x - 0.5), abs(p.y - 0.5))
                  for p in (w2cv(sc, cam, c) for c in corners_w))
        if dev <= 0.44:                      # 6% margin inside the frame
            return r, dev
        r *= (dev / 0.44) * 1.02
    return r, dev

for name, az in VIEWS:
    r, dev = fit_radius(math.radians(az))
    if dev > 0.5:
        raise SystemExit(f"REFUSED: view {name} cannot be framed (dev={dev:.3f})")
    sc.render.filepath = os.path.join(OUTD, f"{az:03d}_{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"wrote {sc.render.filepath}  radius={r:.2f} fit_dev={dev:.3f}")

print("PROOF_VIEWS_DONE")
