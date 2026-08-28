"""qc_studio8.py — reviewer-spec QC renders: 8 named views x selectable passes.

Built 2026-08-27 from the owner-relayed review of the RF67 Golf proof sheet.
Every complaint it answers is a parameter here, so the fix is inspectable:

  * "far too dark / weak lighting"  -> world 0.32, FOUR long strip area lights
    (two overhead longitudinal, one high strip per side). Clay pass renders a
    neutral mid-grey semi-gloss so strip reflections zebra across the panels —
    that is what makes surface waviness readable.
  * "vehicle too small, fill 75-85%" -> per-view radius fitted against the
    PROJECTED MESH VERTICES (not bbox corners — in a 3/4 view the bbox is far
    wider than the car, which is exactly why proof_views framed small). The
    fit moves BOTH directions toward a target span of 0.80 of the frame.
  * "inconsistent framing"          -> every view is fitted to the same fill
    fraction; that is the automotive-QC meaning of consistent framing.
  * "no technical proof"            -> passes: clay, tex, normals (world-space
    colourmap), orient (backface red / front blue — Cycles has no overlay,
    the recorded faceorient pattern), wire (Wireframe node).

Standard view transform, never AgX. Floor is real geometry in clay/tex so the
contact shadow is honest; hidden in the diagnostic passes.

Run: blender -b --python qc_studio8.py -- <car.glb> <outdir> <passes> [res] [samples]
     passes = comma list from {clay,tex,normals,orient,wire}
"""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD = argv[0], argv[1]
PASSES = argv[2].split(",") if len(argv) > 2 else ["clay"]
RES = int(argv[3]) if len(argv) > 3 else 2048
SAMPLES = int(argv[4]) if len(argv) > 4 else 40
FILL = float(os.environ.get("QC_FILL", "0.80"))
# Exposure knobs. The defaults were calibrated on the CLAY pass; a near-black
# textured car swallows them ("the lighting is dark" — owner, 2026-08-27).
# A dark car reads through its speculars and its separation from the ground,
# so the tex-pass levers are world brightness, strip energy and floor tone.
# CALIBRATED FOR A DARK CAR (RF67, measured): QC_WORLD=0.45 QC_LIGHT=2.4
# QC_FLOOR=0.42 puts the car zone at mean ~70-100 with p95 ~200-233 and the
# background at 179 — the black car reads through separation and speculars.
# The paint itself is near-black in the baked texture; brightening past this
# falsifies the colour rather than revealing more.
WORLD = float(os.environ.get("QC_WORLD", "0.32"))
LIGHT = float(os.environ.get("QC_LIGHT", "1.0"))
FLOOR_TONE = float(os.environ.get("QC_FLOOR", "0.30"))

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

# world-space vertex sample for the frame fit (every Nth vertex is plenty)
verts_w = []
for o in meshes:
    mw = o.matrix_world
    vs = o.data.vertices
    step = max(1, len(vs) // 4000)
    for i in range(0, len(vs), step):
        verts_w.append(mw @ vs[i].co)
print(f"fit sample: {len(verts_w)} vertices")

# ---- bright neutral studio ------------------------------------------------
world = bpy.data.worlds.new("w")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (WORLD, WORLD, WORLD, 1.0)
bg.inputs[1].default_value = 1.0

bpy.ops.mesh.primitive_plane_add(size=diag * 6, location=(ctr.x, ctr.y, lo.z))
floor = bpy.context.active_object
fm = bpy.data.materials.new("floor")
fm.use_nodes = True
fb = fm.node_tree.nodes["Principled BSDF"]
fb.inputs["Base Color"].default_value = (FLOOR_TONE, FLOOR_TONE, FLOOR_TONE * 1.03, 1)
fb.inputs["Roughness"].default_value = 0.7
floor.data.materials.append(fm)

# four STRIP lights: two overhead running the car's length, one per side.
L = max(range(3), key=lambda i: ext[i])          # length axis index
strips = (
    ("top_a", (0, -diag * 0.30, diag * 1.05), 5.5),
    ("top_b", (0,  diag * 0.30, diag * 1.05), 5.5),
    ("side_l", (0, -diag * 1.25, diag * 0.55), 3.2),
    ("side_r", (0,  diag * 1.25, diag * 0.55), 3.2),
)
for name, (dx, dy, dz), energy in strips:
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size = diag * 1.6          # long axis
    # 0.30, not 0.12: at x2.4 energy the thin strip's specular image CLIPPED
    # on the clearcoat (reviewer: "clipped white reflections on the bonnet,
    # roof and windscreen"). Measured first: the texture up top is dark
    # (min-ch p95 <= 62), so the whites were RENDER speculars — the fix is a
    # larger source at the same flux (lower radiance, softer highlight), not
    # texture surgery. The Clio rule: measure the pixels before "fixing" a
    # highlight.
    ld.size_y = diag * 0.30
    ld.energy = energy * LIGHT * diag * diag
    lob = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(lob)
    off = mathutils.Vector((dx, dy, dz))
    if L == 1:                    # length on Y: rotate rig 90 deg
        off = mathutils.Vector((off.y, off.x, off.z))
    lob.location = ctr + off
    lob.location.z = lo.z + dz
    d = ctr - lob.location
    lob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if L == 0:                    # align strip long axis with car length
        lob.rotation_euler.rotate_axis("Z", math.radians(90))

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = SAMPLES
sc.cycles.device = "CPU"
try:
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    print("QC_DENOISE: ON (OpenImageDenoise)")
except (TypeError, AttributeError) as e:
    sc.cycles.use_denoising = False
    print(f"QC_DENOISE: OFF ({type(e).__name__}: {e})")
sc.view_settings.view_transform = "Standard"
sc.render.resolution_x = sc.render.resolution_y = RES

cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 85
cam = bpy.data.objects.new("cam", cam_d)
bpy.context.collection.objects.link(cam)
sc.camera = cam

VIEWS = [("front", 0), ("front_left", 45), ("left", 90), ("rear_left", 135),
         ("rear", 180), ("rear_right", 225), ("right", 270), ("front_right", 315)]
elev = math.radians(10)


def place(a_rad, r):
    off = mathutils.Vector((math.cos(a_rad) * r * math.cos(elev),
                            math.sin(a_rad) * r * math.cos(elev),
                            r * math.sin(elev)))
    if L == 1:
        off = mathutils.Vector((off.y, off.x, off.z))
    cam.location = ctr + off
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()


def fit_radius(a_rad):
    """Move the camera until the projected car spans FILL of the frame."""
    from bpy_extras.object_utils import world_to_camera_view as w2cv
    r = diag * 1.2
    span = 0.0
    for _ in range(5):
        place(a_rad, r)
        xs, ys = [], []
        for v in verts_w:
            p = w2cv(sc, cam, v)
            xs.append(p.x)
            ys.append(p.y)
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if abs(span - FILL) < 0.02:
            return r, span
        r *= span / FILL            # zoom IN as well as out
    return r, span


# ---- pass materials -------------------------------------------------------
def clay_mat():
    m = bpy.data.materials.new("qc_clay")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.42, 0.42, 0.42, 1)
    b.inputs["Roughness"].default_value = 0.32
    b.inputs["Metallic"].default_value = 0.0
    return m


def emit(node_builder, name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs[0])
    node_builder(nt, em)
    return m


def normals_mat():
    def build(nt, em):
        g = nt.nodes.new("ShaderNodeNewGeometry")
        mul = nt.nodes.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY_ADD"
        mul.inputs[1].default_value = (0.5, 0.5, 0.5)
        mul.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(g.outputs["Normal"], mul.inputs[0])
        nt.links.new(mul.outputs[0], em.inputs[0])
    return emit(build, "qc_normals")


def orient_mat():
    def build(nt, em):
        g = nt.nodes.new("ShaderNodeNewGeometry")
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.inputs[1].default_value = (0.05, 0.15, 0.85, 1)   # front face: blue
        mix.inputs[2].default_value = (0.90, 0.08, 0.05, 1)   # backface: red
        nt.links.new(g.outputs["Backfacing"], mix.inputs[0])
        nt.links.new(mix.outputs[0], em.inputs[0])
    return emit(build, "qc_orient")


def wire_mat():
    def build(nt, em):
        w = nt.nodes.new("ShaderNodeWireframe")
        w.use_pixel_size = True
        w.inputs[0].default_value = 1.2
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.inputs[1].default_value = (0.82, 0.82, 0.82, 1)
        mix.inputs[2].default_value = (0.02, 0.02, 0.02, 1)
        nt.links.new(w.outputs[0], mix.inputs[0])
        nt.links.new(mix.outputs[0], em.inputs[0])
    return emit(build, "qc_wire")


PASS_DEF = {
    "clay":    (clay_mat,   True,  SAMPLES),
    "tex":     (None,       True,  SAMPLES),
    "normals": (normals_mat, False, 12),
    "orient":  (orient_mat, False, 12),
    "wire":    (wire_mat,   False, 12),
}

# IDENTICAL FRAMING ACROSS VIEWS (reviewer, 2026-08-27): per-view fill makes
# the straight views appear much larger than the sides. QC_CONSTANT=1 (the
# default) fits every view, then uses the LARGEST radius for all eight, so
# apparent scale is identical; the side views set the fill and the straight
# views sit smaller inside the same scale. QC_CONSTANT=0 restores per-view fill.
CONSTANT = os.environ.get("QC_CONSTANT", "1") == "1"
R_SHARED = None
if CONSTANT:
    fits = {az: fit_radius(math.radians(az))[0] for _, az in VIEWS}
    R_SHARED = max(fits.values())
    print("constant framing: shared radius %.2f" % R_SHARED)

# QC_VIEWS renders a SUBSET by name ("front_left,rear_right"). Renders are the
# bottleneck in any comparison round — eight views x several passes is ~40 min
# on 4 cores — and most rounds only need the one view where the defect lives.
#
# IT IS FILTERED HERE, AFTER R_SHARED, AND THAT ORDERING IS THE WHOLE POINT.
# The shared radius is the MAX over all eight fits, so filtering VIEWS before
# it would recompute the max over the subset and silently reframe the car. A
# subset render would then be un-comparable with the full pack it is supposed
# to be checked against — and this session already threw away a before/after
# comparison for exactly that reason ("my first comparison was INVALID because
# framing changed between packs", 2026-08-27). Framing stays a property of the
# car, never of which views were asked for.
_want = os.environ.get("QC_VIEWS")
if _want:
    keep = [v.strip() for v in _want.split(",") if v.strip()]
    known = {n for n, _ in VIEWS}
    unknown = [k for k in keep if k not in known]
    if unknown:
        raise SystemExit(f"REFUSED: unknown view(s) {unknown}; known: {sorted(known)}")
    VIEWS = [(n, a) for n, a in VIEWS if n in keep]
    print("QC_VIEWS subset:", [n for n, _ in VIEWS],
          "(framing still fitted over all 8)")

for pname in PASSES:
    if pname not in PASS_DEF:
        raise SystemExit(f"REFUSED: unknown pass {pname}")
    mat_fn, want_floor, smp = PASS_DEF[pname]
    bpy.context.view_layer.material_override = mat_fn() if mat_fn else None
    floor.hide_render = not want_floor
    sc.cycles.samples = smp
    pdir = os.path.join(OUTD, pname)
    os.makedirs(pdir, exist_ok=True)
    for name, az in VIEWS:
        if CONSTANT:
            r = R_SHARED
            place(math.radians(az), r)
        else:
            r, span = fit_radius(math.radians(az))
            if not (FILL - 0.08 <= span <= FILL + 0.08):
                raise SystemExit(f"REFUSED: {pname}/{name} span={span:.3f} "
                                 f"(target {FILL}) — car not framed")
        sc.render.filepath = os.path.join(pdir, f"{az:03d}_{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"wrote {sc.render.filepath}  r={r:.2f}")

print("QC_STUDIO8_DONE")
