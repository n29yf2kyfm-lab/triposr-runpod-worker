#!/usr/bin/env python3
"""seg_project.py — project 2D class masks onto mesh faces and vote.

For every face centroid: transform into each view's camera, z-buffer test
against the Blender depth EXR (self-calibrating between the two depth
conventions — ray length vs -z), read the class masks at that pixel, and
majority-vote across the views that actually saw the face. Physical priors
then veto impossible assignments (lamps outside the nose/tail bands, glass
below the sill), a neighbour-majority smoothing pass cleans speck noise,
and small islands are absorbed.

Outputs <out_prefix>_labels.npy (int8 per face: 0 body, 1 glass, 2 wheel,
3 lamp, 4 interior/unseen) and prints the face-share table with the glass
band gate (2.5–9.5%, the real-car band).

Run: python3 seg_project.py <canon.glb> <views_dir> <out_prefix>
"""
import json, os, sys
import numpy as np
import trimesh
import OpenEXR, Imath
from PIL import Image

GLB, VIEWS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4
NAMES = np.array(["body", "glass", "wheel", "lamp", "interior"])

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center.astype(np.float64)          # (F,3) world = glTF Y-up
F = len(cent)
print(f"mesh: {F} faces")

# Blender's glTF importer converts Y-up -> Z-up: (x,y,z)_gltf -> (x,-z,y)_blender.
# The cameras were saved in BLENDER world space, so move centroids there first.
bcent = np.stack([cent[:, 0], -cent[:, 2], cent[:, 1]], 1)

cams = json.load(open(os.path.join(VIEWS, "cameras.json")))


def read_depth(fp):
    ex = OpenEXR.InputFile(fp)
    hdr = ex.header(); dw = hdr["dataWindow"]
    W = dw.max.x - dw.min.x + 1; H = dw.max.y - dw.min.y + 1
    ch = "R" if "R" in hdr["channels"] else list(hdr["channels"])[0]
    return np.frombuffer(ex.channel(ch, Imath.PixelType(Imath.PixelType.FLOAT)),
                         dtype=np.float32).reshape(H, W)


votes = np.zeros((F, 4), np.int16)       # body, glass, wheel, lamp
seen = np.zeros(F, np.int16)

for vname, c in cams.items():
    W2C = np.array(c["world_to_camera"]); f = c["focal_px"]; R = c["res"]
    depth = read_depth(os.path.join(VIEWS, c["depth_exr"]))
    pc = (W2C[:3, :3] @ bcent.T).T + W2C[:3, 3]       # camera space, cam looks -Z
    z = -pc[:, 2]
    ok = z > 1e-6
    u = (R / 2 + f * pc[:, 0] / z).round().astype(int)
    v = (R / 2 - f * pc[:, 1] / z).round().astype(int)
    ok &= (u >= 0) & (u < R) & (v >= 0) & (v < R)
    ray = np.linalg.norm(pc, axis=1)
    dpx = np.full(F, 1e10, np.float32)
    dpx[ok] = depth[v[ok], u[ok]]
    tol = 0.02 * float(ray[ok].mean())
    vis_z = ok & (np.abs(dpx - z) < tol)
    vis_r = ok & (np.abs(dpx - ray) < tol)
    vis = vis_z if vis_z.sum() >= vis_r.sum() else vis_r   # self-calibrate
    masks = {}
    for i, cls in ((GLASS, "glass"), (WHEEL, "wheel"), (LAMP, "lamp")):
        fp = os.path.join(VIEWS, f"{vname}_{cls}.png")
        masks[i] = np.array(Image.open(fp)) > 127
    lab = np.zeros(F, np.int8)                          # default body
    for i in (LAMP, GLASS, WHEEL):                      # wheel wins overlaps
        sel = vis.copy(); sel[vis] = masks[i][v[vis], u[vis]]
        lab[sel] = i
    idx = np.where(vis)[0]
    votes[idx, lab[idx]] += 1
    seen += vis
    print(f"{vname}: vis {int(vis.sum())} "
          f"({'z' if vis is vis_z else 'ray'}-depth)", flush=True)

label = np.full(F, UNSEEN, np.int8)
has = seen > 0
label[has] = votes[has].argmax(1)
# a face is non-body only when that class won an outright majority of its views
maj = votes.max(1) * 2 > seen
label[has & ~maj] = BODY

# ---- physical priors (glTF Y-up; X = length on the canonical Pixal pose)
x, y = cent[:, 0], cent[:, 1]
L0, L1 = x.min(), x.max(); L = L1 - L0
H0, H1 = y.min(), y.max(); Hh = H1 - H0
xf = (x - L0) / L; yf = (y - H0) / Hh
lamp_zone = (xf < 0.18) | (xf > 0.82)
label[(label == LAMP) & ~lamp_zone] = BODY
label[(label == GLASS) & (yf < 0.30)] = BODY
label[(label == WHEEL) & (yf > 0.55)] = BODY

# ---- neighbour-majority smoothing + island absorption
adj = m.face_adjacency
neigh = [[] for _ in range(F)]
for a, b in adj:
    neigh[a].append(b); neigh[b].append(a)
from collections import Counter
for _ in range(4):
    new = label.copy()
    for i in range(F):
        cnt = Counter(label[j] for j in neigh[i]); cnt[label[i]] += 1
        new[i] = cnt.most_common(1)[0][0]
    if (new == label).all():
        break
    label = new
# absorb small islands into their surrounding label (single scan per label,
# NOT per island -- the vx1 transfer paid 4 CPU-hours for that mistake)
import scipy.sparse as sp
n = F
for target in range(5):
    mask = label == target
    if not mask.any():
        continue
    same = mask[adj[:, 0]] & mask[adj[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])), shape=(n, n))
    ncomp, comp = sp.csgraph.connected_components(g + g.T, directed=False)
    comp = comp.copy(); comp[~mask] = -1
    sizes = Counter(comp[mask])
    small = {cid for cid, cnt in sizes.items() if cnt < 400}
    if not small:
        continue
    border_vote = {cid: Counter() for cid in small}
    for a, b in adj:
        ca, cb = comp[a], comp[b]
        if ca in small and cb != ca:
            border_vote[ca][label[b]] += 1
        if cb in small and ca != cb:
            border_vote[cb][label[a]] += 1
    for cid, cnt in border_vote.items():
        if cnt:
            label[comp == cid] = cnt.most_common(1)[0][0]

np.save(f"{OUT}_labels.npy", label)
share = {str(NAMES[i]): round(100 * float((label == i).mean()), 2) for i in range(5)}
print("face share:", share)
g = share["glass"]
print(f"GLASS BAND GATE (2.5-9.5%): {'PASS' if 2.5 <= g <= 9.5 else 'FAIL'} at {g}%")
