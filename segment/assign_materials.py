"""Step B — apply per-face labels to the CLEANED mesh, smooth the boundary,
assign body/glass/trim materials, export the recolourable GLB.

Usage: blender -b -P seg_stepB_assign.py -- <work_dir> out.glb [paint_hex]
"""
import bpy, sys, numpy as np, bmesh
from collections import deque

argv = sys.argv[sys.argv.index("--")+1:]
WORK, OUTP = argv[0], argv[1]
PAINT_HEX = argv[2] if len(argv) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=f"{WORK}/cleaned.glb")
obj = next(o for o in bpy.data.objects if o.type == "MESH")
me = obj.data
N = len(me.polygons)
lab = np.load(f"{WORK}/labels.npy")
assert len(lab) == N, "label/mesh face-count mismatch (%d vs %d)" % (len(lab), N)
gz = np.load(f"{WORK}/geom.npz")
zc = gz["zc"]; nup = gz["nup"] if "nup" in gz else np.zeros(N)

# adjacency
bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
nbr = [[] for _ in range(N)]
for e in bm.edges:
    lf = e.link_faces
    if len(lf) == 2:
        a, b = lf[0].index, lf[1].index; nbr[a].append(b); nbr[b].append(a)
bm.free()

# majority-vote smoothing (clean the vote noise / boundary)
for _ in range(5):
    new = lab.copy()
    for i in range(N):
        ns = nbr[i]
        if not ns: continue
        cnt = np.bincount(lab[ns], minlength=4); d = cnt.argmax()
        if cnt[d] >= max(3, int(0.6*len(ns))) and d != lab[i]:
            new[i] = d
    lab = new

def comps(mask):
    seen = np.zeros(N, bool); out = []
    for s in range(N):
        if mask[s] and not seen[s]:
            dq = deque([s]); seen[s] = True; c = [s]
            while dq:
                x = dq.popleft()
                for m in nbr[x]:
                    if mask[m] and not seen[m]: seen[m] = True; dq.append(m); c.append(m)
            out.append(c)
    return out
# morphological close on glass: dilate into body then erode -> fills the red
# interior holes inside windows and smooths the boundary
def dilate(mask, into):
    add = np.zeros(N, bool)
    for i in np.where(mask)[0]:
        for m in nbr[i]:
            if into[m]: add[m] = True
    return mask | add
def erode(mask):
    out = mask.copy()
    for i in np.where(mask)[0]:
        if any(not mask[m] for m in nbr[i]): out[i] = False
    return out
g = (lab == 2)
for _ in range(3): g = dilate(g, lab == 1)
for _ in range(3): g = erode(g)
lab[(lab == 2) & (~g)] = 1
lab[g] = 2
# fill enclosed holes: any body component whose entire boundary touches glass is
# an interior speckle inside a window -> glass (premium: solid window panes)
for c in comps(lab == 1):
    if len(c) >= 4000:
        continue
    border = set()
    for f in c:
        for m in nbr[f]:
            if lab[m] != 1: border.add(lab[m])
    if border and border <= {2}:
        for f in c: lab[f] = 2
for c in comps(lab == 2):                       # tiny glass specks -> body
    if len(c) < 500:
        for f in c: lab[f] = 1
for c in comps(lab == 3):                       # tiny wheel specks -> body
    if len(c) < 800:
        for f in c: lab[f] = 1

# materials
orig = me.materials[0]; orig.name = "trim"
body = orig.copy(); body.name = "body"
glass = bpy.data.materials.new("glass"); glass.use_nodes = True
gb = next(n for n in glass.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
gb.inputs["Base Color"].default_value = (0.03, 0.035, 0.045, 1)
for k in ("Transmission", "Transmission Weight"):
    if k in gb.inputs: gb.inputs[k].default_value = 0.9
gb.inputs["Roughness"].default_value = 0.14
if "IOR" in gb.inputs: gb.inputs["IOR"].default_value = 1.5
if "Alpha" in gb.inputs: gb.inputs["Alpha"].default_value = 0.45
glass.blend_method = "BLEND"
me.materials.append(body); BODY_I = len(me.materials)-1
me.materials.append(glass); GLASS_I = len(me.materials)-1
for p in me.polygons:
    if lab[p.index] == 1: p.material_index = BODY_I
    elif lab[p.index] == 2: p.material_index = GLASS_I
    # trim + wheel keep original (index 0)

if PAINT_HEX:
    hx = PAINT_HEX.lstrip("#"); R, G, B = [int(hx[i:i+2], 16)/255 for i in (0, 2, 4)]
    bb = next(n for n in body.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bc = bb.inputs["Base Color"]
    for l in list(bc.links): body.node_tree.links.remove(l)
    bc.default_value = (R, G, B, 1)
    bb.inputs["Metallic"].default_value = 0.2
    bb.inputs["Roughness"].default_value = 0.45

bpy.ops.export_scene.gltf(filepath=OUTP, export_format='GLB',
    export_apply=True, use_selection=False, export_yup=True,
    export_draco_mesh_compression_enable=False)
print("STEPB_DONE body=%d glass=%d wheel(trim)=%d -> %s" % ((lab == 1).sum(), (lab == 2).sum(), (lab == 3).sum(), OUTP))
