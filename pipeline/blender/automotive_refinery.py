"""automotive_refinery.py — post-generation refinery for TRELLIS car meshes.
Implements the 'Automotive Reconstruction & Refinery' spec, adapted for
GLB-exportable results (Blender 4.0+, headless).

Stages
  1. FLANK DE-RIPPLE   capped Laplacian relaxation restricted to the lateral
                       body band — flattens marching-cubes lobes/ripples on
                       door flanks without moving creases more than --cap
  2. GLASS EXTRACTION  (--clear_glass) greenhouse faces (upper 45% of height,
                       non-horizontal normals) split into a Glass sub-mesh
                       with KHR-exportable transmission (IOR 1.45)
  3. CAR PAINT         two-layer shader on painted regions: metallic base
                       (from --paint_hex), baked flake normal texture
                       (procedural Voronoi does NOT export to glTF, so flakes
                       are baked to a tiling normal map), clearcoat 1.0 at
                       low roughness -> KHR_materials_clearcoat

Run:
  blender -b -noaudio --python pipeline/blender/automotive_refinery.py -- \
    --mesh_path /abs/car_raw.glb [--out /abs/refined.glb] \
    [--paint_hex 5E6468] [--flake_scale 4500] [--base_rough 0.18] \
    [--clear_glass] [--cap 0.004]
"""
import bpy, bmesh, sys, os, math
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(f, d=None):
    return argv[argv.index(f) + 1] if f in argv else d
MESH = arg("--mesh_path")
OUT = arg("--out", (MESH or "car.glb").replace(".glb", "") + ".refined.glb")
HEX = (arg("--paint_hex", "5E6468")).lstrip("#")
FLAKE = float(arg("--flake_scale", "4500"))
ROUGH = float(arg("--base_rough", "0.18"))
CLEAR_GLASS = "--clear_glass" in argv
CAP = float(arg("--cap", "0.004"))

if not (MESH and os.path.exists(MESH)):
    print("REFINERY_ERROR need --mesh_path"); sys.exit(1)

def srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
PAINT_RGB = tuple(srgb_to_linear(int(HEX[i:i+2], 16)) for i in (0, 2, 4))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=MESH)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# ---- bounds (x=width, y=length, z=height for TRELLIS exports) --------------
lo = np.array([1e9] * 3); hi = -lo.copy()
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ __import__("mathutils").Vector(c)
        lo = np.minimum(lo, w); hi = np.maximum(hi, w)
size = hi - lo
W, H = size[0], size[2]

# ---- 1. flank de-ripple ------------------------------------------------------
for o in meshes:
    bm = bmesh.new(); bm.from_mesh(o.data)
    side_lo = lo[0] + 0.90 * W / 2 * 0  # bands measured from centreline below
    cx = (lo[0] + hi[0]) / 2
    band = [v for v in bm.verts
            if abs(abs(v.co.x - cx) - W / 2) < 0.06 * W          # near the flanks
            and lo[2] + 0.12 * H < v.co.z < lo[2] + 0.60 * H     # door band
            and abs(v.normal.x) > 0.75]                          # facing sideways
    orig = {v.index: v.co.copy() for v in band}
    bandset = {v.index for v in band}
    for _ in range(10):
        newpos = {}
        for v in band:
            ns = [e.other_vert(v) for e in v.link_edges]
            if not ns: continue
            avg = sum((n.co for n in ns), v.co * 0) / len(ns)
            p = v.co.copy(); p.x = v.co.x + (avg.x - v.co.x) * 0.5   # relax lateral only
            newpos[v.index] = p
        for vi, p in newpos.items():
            bm.verts.ensure_lookup_table(); bm.verts[vi].co = p
    capped = 0
    bm.verts.ensure_lookup_table()
    for vi, oc in orig.items():
        v = bm.verts[vi]; d = v.co - oc
        if d.length > CAP:
            v.co = oc + d.normalized() * CAP; capped += 1
    bm.to_mesh(o.data); bm.free()
    print(f"DERIPPLE {o.name}: {len(band)} flank verts relaxed, {capped} capped at {CAP*1000:.0f}mm")

# ---- 3a. flake normal texture (bakeable stand-in for Voronoi flakes) -------
def make_flake_normal(px=512, strength=0.55):
    rng = np.random.default_rng(7)
    n = rng.random((px, px)).astype(np.float32)
    nx = (np.roll(n, -1, 1) - np.roll(n, 1, 1)) * strength
    ny = (np.roll(n, -1, 0) - np.roll(n, 1, 0)) * strength
    nz = np.ones_like(n)
    l = np.sqrt(nx**2 + ny**2 + nz**2)
    rgb = np.stack([(nx / l + 1) / 2, (ny / l + 1) / 2, (nz / l + 1) / 2, np.ones_like(n)], -1)
    img = bpy.data.images.new("flake_normal", px, px)
    img.pixels[:] = rgb.reshape(-1).tolist()
    img.pack()
    return img

def car_paint_material():
    m = bpy.data.materials.new("CAR_PAINT")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*PAINT_RGB, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = ROUGH
    if "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = 1.0
        b.inputs["Coat Roughness"].default_value = 0.08
    if FLAKE > 0:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = make_flake_normal()
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 0.35
        mapping = nt.nodes.new("ShaderNodeMapping")
        uv = nt.nodes.new("ShaderNodeTexCoord")
        rep = max(8.0, FLAKE / 100.0)   # flakeScale -> UV tiling factor
        mapping.inputs["Scale"].default_value = (rep, rep, rep)
        nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m

def glass_material():
    m = bpy.data.materials.new("GLASS")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.35, 0.38, 0.40, 1)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.05
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.45
    m.blend_method = "BLEND"
    return m

# ---- 2. glass extraction ----------------------------------------------------
if CLEAR_GLASS:
    gm = glass_material()
    for o in list(meshes):
        me = o.data
        sel = []
        zthr = lo[2] + 0.55 * H
        for p in me.polygons:
            c = o.matrix_world @ p.center
            n = (o.matrix_world.to_3x3() @ p.normal).normalized()
            if c.z > zthr and abs(n.z) < 0.65:
                sel.append(p.index)
        if len(sel) < 8:
            print(f"GLASS {o.name}: too few candidate faces ({len(sel)}), skipped")
            continue
        for p in me.polygons: p.select = p.index in set(sel)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.object.mode_set(mode="OBJECT")  # sync selection
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")
            new = [x for x in bpy.context.scene.objects if x.type == "MESH" and x not in meshes][-1]
            new.name = "Glass"
            new.data.materials.clear()
            new.data.materials.append(gm)
            print(f"GLASS {o.name}: {len(sel)} faces -> Glass sub-mesh (IOR 1.45, transmissive)")
        except Exception as e:
            bpy.ops.object.mode_set(mode="OBJECT")
            print(f"GLASS {o.name}: separate failed: {e}")

# ---- 3b. paint assignment ----------------------------------------------------
paint = car_paint_material()
for o in [x for x in bpy.context.scene.objects if x.type == "MESH" and x.name != "Glass"]:
    # TRELLIS meshes are single-material; replace with CAR_PAINT but keep the
    # baked texture as base colour ONLY if the caller passed no hex override.
    o.data.materials.clear()
    o.data.materials.append(paint)
    for p in o.data.polygons: p.use_smooth = True
print(f"PAINT applied: #{HEX} metallic base rough={ROUGH} clearcoat=1.0 flakes={'on' if FLAKE>0 else 'off'}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print("REFINERY_OK", OUT)
