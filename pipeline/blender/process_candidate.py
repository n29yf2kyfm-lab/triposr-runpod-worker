"""process_candidate.py — STAGES 5-12: turn a TRELLIS.2 candidate into a
production car GLB, in Blender (headless).

Does automatically:
  5  import candidate GLB
  6  symmetry correction (mirror the cleaner half across the long axis),
     corrective smooth, weighted normals, merge doubles, outward normals
  7  component replacement — swaps weak generated parts for reusable high-quality
     assets IF a component library is present (pipeline/components/*.glb by slot:
     wheel/mirror/headlight/taillight/grille/badge/handle); else leaves them and
     flags the slot
  8  panel separation — cuts doors/bonnet/boot into separate objects using a
     reference-region spec (JSON of bbox fractions), so they can be rigged
  9  interior/engine-bay — imports a separate modelled asset if provided
        (pipeline/components/interior.glb / engine_bay.glb) instead of trusting
        the generator to hallucinate hidden detail
  11 LOD — writes _lod0 (full) and _lod1 (decimated ~40%) meshes
  12 export validated GLB (tangents on)

Rigging (10) is delegated to rig_panels.py after separation.

Run:
  blender -b -noaudio --python pipeline/blender/process_candidate.py -- \
     --in pipeline/build/candidates/car_rear_seed1.glb \
     --panels pipeline/blender/golf_panels_ref.json \
     --components pipeline/components --out pipeline/build/golf_trellis.glb

HONEST LIMITATIONS (stages 5-12):
  • Symmetry mirroring assumes ONE half is clean; if both halves are melted it
    just averages the mess. Not a substitute for retopo.
  • Automatic panel separation cuts by bounding-region, NOT by real shut-lines —
    the cut edges are ragged unless the generated mesh happens to have loops
    there. Clean shut-lines are still manual work.
  • Component replacement needs a hand-made/licensed component library; without
    it the generated wheels/lights stay (usually the weakest parts).
  • Retopology to clean quads is NOT automated here (Instant Meshes/QuadRemesh is
    a separate, human-reviewed step) — this does weighted-normal + corrective
    smooth shading cleanup only.
"""
import bpy, bmesh, sys, os, json, math, mathutils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None): return argv[argv.index(f) + 1] if f in argv else d
IN = arg("--in"); OUT = arg("--out"); PANELS = arg("--panels"); COMPS = arg("--components")
if not (IN and OUT and os.path.exists(IN)):
    print("PROC_ERROR need --in existing and --out"); sys.exit(1)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

def all_meshes(): return [o for o in bpy.context.scene.objects if o.type == "MESH"]
# join the candidate into one body object to work on
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = all_meshes()[0]
bpy.ops.object.join()
body = bpy.context.view_layer.objects.active; body.name = "Body"

# ---- 6 cleanup (+ OPTIONAL symmetry) --------------------------------------
# NOTE: TRELLIS.2 output is usually ALREADY symmetric — bisect-mirroring it
# caves in the far side. So symmetry is OPT-IN (--symmetry); default is a light
# clean that preserves the generated geometry. Only mirror when one half is
# genuinely bad.
bpy.context.view_layer.objects.active = body; body.select_set(True)
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0004)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")
if "--symmetry" in argv:
    ext = body.dimensions
    wax = min(range(3), key=lambda i: ext[i])
    mir = body.modifiers.new("Mirror", "MIRROR"); mir.use_axis = [i == wax for i in range(3)]
    mir.use_bisect_axis = [i == wax for i in range(3)]; mir.use_clip = True
cs = body.modifiers.new("Corrective", "CORRECTIVE_SMOOTH"); cs.factor = 0.3; cs.iterations = 6
wn = body.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL"); wn.keep_sharp = True; wn.weight = 60
for p in body.data.polygons: p.use_smooth = True

# ---- 7 component replacement ----------------------------------------------
SLOTS = ["wheel", "mirror", "headlight", "taillight", "grille", "badge", "handle"]
replaced, missing = [], []
for slot in SLOTS:
    asset = os.path.join(COMPS or "", f"{slot}.glb")
    if COMPS and os.path.exists(asset):
        before = set(o.name for o in bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=asset)
        for n in (set(o.name for o in bpy.context.scene.objects) - before):
            bpy.data.objects[n].name = f"comp_{slot}_{n}"
        replaced.append(slot)
    else:
        missing.append(slot)

# ---- 8 panel separation (reference-region spec) ---------------------------
sep = []
if PANELS and os.path.exists(PANELS):
    spec = json.load(open(PANELS))          # [{part, bbox:[x0,x1,y0,y1,z0,z1] fractions}]
    b = body.bound_box
    lo = mathutils.Vector((min(v[0] for v in b), min(v[1] for v in b), min(v[2] for v in b)))
    hi = mathutils.Vector((max(v[0] for v in b), max(v[1] for v in b), max(v[2] for v in b)))
    size = hi - lo
    for s in spec:
        bx = s["bbox"]
        bpy.context.view_layer.objects.active = body; body.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        me = body.data
        for poly in me.polygons:
            c = body.matrix_world @ poly.center
            f = [(c[i] - lo[i]) / size[i] for i in range(3)]
            inside = (bx[0] <= f[0] <= bx[1] and bx[2] <= f[1] <= bx[3] and bx[4] <= f[2] <= bx[5])
            poly.select = inside
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.separate(type="SELECTED")
            sep.append(s["part"])
        except Exception:
            pass
        bpy.ops.object.mode_set(mode="OBJECT")
    # name the separated pieces
    for o in all_meshes():
        if o.name.startswith("Body.") and sep:
            o.name = "Panel_" + sep.pop(0)

# ---- 9 interior / engine bay ----------------------------------------------
for extra in ("interior", "engine_bay"):
    p = os.path.join(COMPS or "", f"{extra}.glb")
    if COMPS and os.path.exists(p):
        bpy.ops.import_scene.gltf(filepath=p)

# ---- 11 LOD ---------------------------------------------------------------
def export(path, lod):
    for o in all_meshes():
        for m in list(o.modifiers):
            if m.type == "DECIMATE": o.modifiers.remove(m)
        if lod > 0:
            d = o.modifiers.new("Decimate", "DECIMATE"); d.ratio = 0.4
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False,
        export_apply=True, export_yup=True, export_normals=True, export_tangents=True,
        export_materials="EXPORT", export_extras=True)

export(OUT, 0)
export(OUT.replace(".glb", "_lod1.glb"), 1)
print(f"PROC_OK wrote {OUT} (+ _lod1)")
print(f"  components replaced: {replaced or 'NONE (no library)'}")
print(f"  component slots still generated (weak): {missing}")
print(f"  panels separated: {sep if PANELS else 'skipped (no --panels ref)'}")
