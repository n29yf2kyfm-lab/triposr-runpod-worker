"""Reusable GLB fixer: (1) re-upright to canonical orientation (smallest extent
-> up, cabin glass on top), (2) separate wheel/tyre objects into a dedicated
material so body recolour can't bleed onto them, (3) bake GB plates, Draco export.
Usage: fix_glb.py in.glb out.glb REG"""
import bpy, bmesh, sys, os, tempfile, re, math
import numpy as np
from mathutils import Matrix
inp, outp, REG = sys.argv[-3], sys.argv[-2], sys.argv[-1]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)
for o in list(bpy.data.objects):
    if o.type == 'MESH' and o.name.split('.')[0] in ("plate_front", "plate_rear", "plate"):
        bpy.data.objects.remove(o, do_unlink=True)

def world_verts():
    V = []
    for o in bpy.data.objects:
        if o.type == 'MESH':
            mw = o.matrix_world
            V += [mw @ v.co for v in o.data.vertices]
    return np.array([[v.x, v.y, v.z] for v in V]) if V else np.zeros((1, 3))

# ===== HARDEN: bake transforms, recalc normals OUTWARD (fix mirrored/negative-scale
# dark renders), normalize extreme scale (fix mis-scale blobs) =====
import bmesh as _bm
# Glass/light/transmissive materials must NOT have their normals recalculated:
# recalc flips authored normals on thin transmissive surfaces and shatters the
# refraction into a camo/leopard mottle (root-caused 2026-07-20 on Cupra Ateca,
# Volvo C30, Toyota Proace). We still bake the world transform on every face and
# recalc normals on OPAQUE body faces (that fixes mirrored/negative-scale dark
# renders); we simply exclude transmissive faces from the recalc.
_TRANS_RE = re.compile(r"(glass|window|windscreen|windshield|screen|scheibe|fenster|vidro|verre|"
                       r"light|lamp|lens|headlight|taillight|tail_light|blinker|indicator|reflector)", re.I)
def _is_transmissive(mat):
    if not mat: return False
    if _TRANS_RE.search(mat.name or ""): return True
    try:
        if mat.blend_method not in ('OPAQUE', 'CLIP'): return True
    except Exception: pass
    if getattr(mat, "use_nodes", False):
        b=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'), None)
        if b:
            for _k in ("Transmission", "Transmission Weight"):
                _i=b.inputs.get(_k)
                if _i is not None and not _i.is_linked and _i.default_value>0.1: return True
            _a=b.inputs.get("Alpha")
            if _a is not None and not _a.is_linked and _a.default_value<0.9: return True
    return False
try:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
except Exception: pass
for _o in [x for x in bpy.data.objects if x.type=='MESH']:
    _prot={i for i,sl in enumerate(_o.material_slots) if _is_transmissive(sl.material)}
    m=_bm.new(); m.from_mesh(_o.data)
    _bm.ops.transform(m, matrix=_o.matrix_world, verts=m.verts)   # bake world transform into verts
    _rfaces=[f for f in m.faces if f.material_index not in _prot] if _prot else m.faces
    if _rfaces: _bm.ops.recalc_face_normals(m, faces=_rfaces)     # outward normals on OPAQUE faces only
    m.to_mesh(_o.data); m.free()
    _o.matrix_world = Matrix.Identity(4)
    _o.data.update()
bpy.context.view_layer.update()
# HARDEN: if a material's base color is driven by an image texture but its base-color
# VALUE is dark, Blender exports baseColorFactor=dark x texture = black panels. Force
# the Principled base-color value to white wherever a base-color image texture is linked.
for _m in bpy.data.materials:
    if not _m.use_nodes: continue
    _b=next((n for n in _m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if not _b: continue
    _bc=_b.inputs.get("Base Color")
    if _bc and _bc.is_linked:
        _m.node_tree.nodes  # ensure
        _bc.default_value=(1,1,1,1)
# normalize only EXTREME scale (blob guard): target longest dim ~4.5m if wildly off
_V = world_verts(); _ext = _V.max(0) - _V.min(0); _ld = float(max(_ext))
if _ld > 0 and (_ld < 1.0 or _ld > 12.0):
    _s = 4.5 / _ld
    for _o in [x for x in bpy.data.objects if x.type=='MESH']:
        _o.scale = (_o.scale[0]*_s, _o.scale[1]*_s, _o.scale[2]*_s)
    bpy.ops.object.select_all(action='SELECT'); bpy.context.view_layer.objects.active=[x for x in bpy.data.objects if x.type=='MESH'][0]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    print(f"SCALE_NORMALIZED from {_ld:.2f} by {_s:.3f}")


# ---- 1. RE-UPRIGHT ----------------------------------------------------------
V = world_verts(); ext = V.max(0) - V.min(0)
up = int(np.argmin(ext))
roots = [o for o in bpy.data.objects if o.parent is None]
def rotate_all(R):
    for o in roots: o.matrix_world = R @ o.matrix_world
    bpy.context.view_layer.update()
if False and up == 0:   rotate_all(Matrix.Rotation(math.radians(-90), 4, 'Y'))
elif False and up == 1: rotate_all(Matrix.Rotation(math.radians(90), 4, 'X'))
# glass on top? if glass centroid sits in bottom half of Z, flip 180 about X
gl = re.compile(r"(glass|window|windscreen|windshield|screen|scheibe|fenster|vidro)", re.I)
V = world_verts(); zmin, zmax = V[:, 2].min(), V[:, 2].max(); H = (zmax - zmin) or 1
gz = []
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    for si, sl in enumerate(o.material_slots):
        if sl.material and gl.search(sl.material.name):
            mw = o.matrix_world
            for p in o.data.polygons:
                if p.material_index == si: gz.append((mw @ p.center).z)
if False and gz and (np.mean(gz) - zmin) / H < 0.45:
    rotate_all(Matrix.Rotation(math.radians(180), 4, 'X'))

# ---- 2. WHEEL SEPARATION ----------------------------------------------------
V = world_verts(); zmin, zmax = V[:, 2].min(), V[:, 2].max(); H = (zmax - zmin) or 1
WHEEL = re.compile(r"(wheel|tyre|tire|\brim\b|alloy|\bhub\b|brake|caliper|reifen|felge|jante|rueda|rubber|disc)", re.I)
def get_mat(name, base, rough, metal):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes = True
    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b:
        b.inputs["Base Color"].default_value = (*base, 1)
        if "Metallic" in b.inputs: b.inputs["Metallic"].default_value = metal
        if "Roughness" in b.inputs: b.inputs["Roughness"].default_value = rough
    return m
rim = get_mat("wheel_rim", (0.56, 0.57, 0.60), 0.42, 0.9)
tyre = get_mat("tyre", (0.02, 0.02, 0.022), 0.85, 0.0)
sep = 0
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    n = o.name.lower()
    # world z-span of this object
    zs = [(o.matrix_world @ v.co).z for v in o.data.vertices]
    if not zs: continue
    top = (max(zs) - zmin) / H
    is_wheel = bool(WHEEL.search(n)) or (top < 0.48 and (max(zs) - min(zs)) / H < 0.42 and len(o.data.vertices) > 50)
    if is_wheel:
        t = tyre if ("tyre" in n or "tire" in n or "rubber" in n) else rim
        o.data.materials.clear(); o.data.materials.append(t)
        for p in o.data.polygons: p.material_index = 0
        sep += 1

# ---- 3. PLATES (front white / rear yellow, auto front by glass centroid) -----
V = world_verts(); lo = V.min(0); hi = V.max(0); c = (lo + hi) / 2
height = hi[2] - lo[2]; zmin = lo[2]
L = 0 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 1; Wd = 1 - L
scale = (hi[L] - lo[L]) / 4.5; pw = 0.52 * scale / 2; ph = 0.11 * scale / 2
Wc = c[Wd]; Zc = zmin + 0.30 * height; size = max(hi[i] - lo[i] for i in range(3))
_ASSETS = os.environ.get("PIPELINE_ASSETS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
def make_plate(rear):
    return os.path.join(_ASSETS, "plate_rear.png" if rear else "plate_front.png")
gzc = None
gz2 = []
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    for si, sl in enumerate(o.material_slots):
        if sl.material and gl.search(sl.material.name):
            for p in o.data.polygons:
                if p.material_index == si: gz2.append((o.matrix_world @ p.center)[L])
if gz2:
    gc = float(np.mean(gz2)); front_end = hi[L] if abs(hi[L] - gc) >= abs(lo[L] - gc) else lo[L]
else:
    front_end = hi[L]
rear_end = lo[L] if front_end == hi[L] else hi[L]
def place(name, end, rear):
    outward = 1.0 if end == hi[L] else -1.0; Lc = end + outward * size * 0.006
    pm = bpy.data.meshes.new(name); bm = bmesh.new()
    def Vx(dw, dz):
        p = [0, 0, 0]; p[L] = Lc; p[Wd] = Wc + dw; p[2] = Zc + dz; return bm.verts.new(p)
    vs = [Vx(-pw, -ph), Vx(-pw, ph), Vx(pw, ph), Vx(pw, -ph)]; f = bm.faces.new(vs)
    uvl = bm.loops.layers.uv.new("UVMap")
    uvs = [(1, 0), (1, 1), (0, 1), (0, 0)] if outward > 0 else [(0, 0), (0, 1), (1, 1), (1, 0)]
    for lp, uv in zip(f.loops, uvs): lp[uvl].uv = uv
    bm.to_mesh(pm); bm.free()
    ob = bpy.data.objects.new(name, pm); bpy.context.collection.objects.link(ob)
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    nt = mat.node_tree; pb = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(make_plate(rear))
    nt.links.new(tex.outputs["Color"], pb.inputs["Base Color"]); pb.inputs["Roughness"].default_value = 0.35
    pm.materials.append(mat)
place("plate_front", front_end, False); place("plate_rear", rear_end, True)
print(f"FIXED up_axis_was={up} wheels_sep={sep} L={L}")
bpy.ops.export_scene.gltf(filepath=outp, export_format='GLB', export_draco_mesh_compression_enable=True,
    export_draco_mesh_compression_level=6, export_apply=True, use_selection=False, export_yup=True)
print("EXPORTED", outp)
