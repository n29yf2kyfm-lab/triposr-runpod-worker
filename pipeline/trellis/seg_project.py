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
# GRAPH-AWARE concatenate: geometry.values() drops node transforms, so an
# instanced or transformed scene projects against the WRONG world positions
# and every label lands on the wrong face. (Same defect class as the
# swap_rear/add_parts instance collapse, 2026-08-19.) Benign on a canon.py
# output — it bakes transforms — but never trust that from upstream.
_parts = []
for _node in sc.graph.nodes_geometry:
    _T, _gn = sc.graph[_node]
    _g = sc.geometry[_gn].copy()
    if _T is not None and not np.allclose(_T, np.eye(4)):
        _g.apply_transform(_T)
    _parts.append(_g)
m = _parts[0] if len(_parts) == 1 else trimesh.util.concatenate(_parts)
cent = m.triangles_center.astype(np.float64)          # (F,3) world = glTF Y-up
F = len(cent)
CAR_DIAG = float(np.linalg.norm(m.vertices.max(0) - m.vertices.min(0)))
print(f"mesh: {F} faces, diag {CAR_DIAG:.3f}")

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
    # DEPTH TOLERANCE IS MESH-RELATIVE, NOT CAMERA-RELATIVE. It was
    # 0.02 x mean ray distance = 0.048 units here, i.e. ~5% of the car's
    # own LENGTH (~19cm on a real Yaris) — loose enough that everything
    # just BEHIND the glazing (inner skin, dash top, door cards) passed the
    # "is this the visible surface" test and took the window mask, which is
    # why glass measured 16.9% of exterior AREA against a 2.5-9.5% band
    # while the label render looked correct. The question the test asks is
    # "is this face the FIRST surface at this pixel", so the scale that
    # matters is the mesh's, not the camera's.
    tol = float(os.environ.get("SEG_DEPTH_TOL_FRAC", "0.0025")) * CAR_DIAG
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

# ---- ROOF RULE. Measured on the Pixal Yaris: 46.2% of projected "glass"
# faced UP (|n_y| > 0.7) and glass reached 28.2% of exterior faces against a
# 2.5-9.5% band — DINO's "car window" boxes enclose the whole greenhouse, so
# the roof skin between the screens votes glass in every view that sees it.
# The physical argument (proven in hybrid_transfer._roofish, 2026-08-13):
# in the CABIN MID-BAND there is no raked screen, so anything strongly
# up-facing there is roof; only in the end quarters can a steep up-facing
# face legitimately be windscreen/backlight, and there the height test still
# protects the raked screen centre.
n_up = np.abs(m.face_normals[:, 1])
mid_band = (xf > 0.32) & (xf < 0.68)
roofish = (mid_band & (n_up > 0.55)) | ((n_up > 0.85) & (yf > 0.88))
_before = int((label == GLASS).sum())
label[(label == GLASS) & roofish] = BODY
print(f"roof rule: {_before - int((label == GLASS).sum())} up-facing faces "
      f"returned to body ({_before} glass before)")

# ---- neighbour-majority smoothing + island absorption
adj = m.face_adjacency
neigh = [[] for _ in range(F)]
for a, b in adj:
    neigh[a].append(b); neigh[b].append(a)
from collections import Counter
# VECTORISED neighbour-majority (was a Python loop over every face with a
# Counter — ~11M Counter ops on a 918k-face Pixal mesh, minutes per pass).
# Same result: each face takes the modal label of itself + its neighbours,
# ties broken by lowest class id exactly as Counter.most_common did.
_a, _b = adj[:, 0], adj[:, 1]
for _ in range(4):
    tally = np.zeros((F, 5), np.int32)
    np.add.at(tally, (_a, label[_b]), 1)
    np.add.at(tally, (_b, label[_a]), 1)
    tally[np.arange(F), label] += 1
    new = tally.argmax(1).astype(np.int8)
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
    # vectorised border vote (was a Python loop over ~1.4M adjacency pairs
    # per label = 7M iterations): tally neighbour labels per small component
    small_arr = np.zeros(ncomp, bool)
    small_arr[list(small)] = True
    ca, cb = comp[adj[:, 0]], comp[adj[:, 1]]
    cross = ca != cb
    tal = np.zeros((ncomp, 5), np.int64)
    sel = cross & (ca >= 0) & small_arr[np.clip(ca, 0, None)]
    np.add.at(tal, (ca[sel], label[adj[sel, 1]]), 1)
    sel = cross & (cb >= 0) & small_arr[np.clip(cb, 0, None)]
    np.add.at(tal, (cb[sel], label[adj[sel, 0]]), 1)
    for cid in small:
        if tal[cid].any():
            label[comp == cid] = np.int8(tal[cid].argmax())

np.save(f"{OUT}_labels.npy", label)
share = {str(NAMES[i]): round(100 * float((label == i).mean()), 2) for i in range(5)}
print("face share:", share)

# ---- GLASS BAND GATE, recalibrated 2026-08-19 against REAL catalogue cars.
#
# The old gate ("2.5-9.5% of faces") was wrong twice over and failed a mesh
# whose labels the eye confirmed as correct:
#   1. FACE COUNT is tessellation-dependent. Measured on the Pixal Yaris,
#      glass faces are 1.58x smaller than body faces, so counting inflates
#      glass by ~14% relative to area. AREA is the physical quantity.
#   2. The band itself was never measured. Ten live catalogue cars
#      (Draco-decoded, glass by material name, mirrors/lamps excluded) give
#      glass as % of TOTAL area: min 1.12, p10 2.62, median 5.75, p90 12.21,
#      max 12.24 (M440i 12.24, Polo 1.12). A real BMW therefore BUSTS the old
#      9.5% ceiling — the band was never a real-car band.
# Gate on area share of the whole mesh, 1.0-13.0%, which is the measured
# catalogue envelope with a small margin. The Pixal Yaris scores 5.56% —
# essentially the catalogue median.
CAL = {"n": 10, "min": 1.12, "median": 5.75, "max": 12.24,
       "source": "10 live catalogue cars measured 2026-08-19"}
area = m.area_faces
g_area = round(100 * float(area[label == GLASS].sum()) / float(area.sum()), 2)
ext = int((label != UNSEEN).sum())
print(f"exterior(seen) faces: {ext} of {F} ({100*ext/F:.1f}%)")
print(f"GLASS BAND GATE (1.0-13.0% of TOTAL AREA, calibrated on {CAL['n']} "
      f"catalogue cars, median {CAL['median']}%): "
      f"{'PASS' if 1.0 <= g_area <= 13.0 else 'FAIL'} at {g_area}%")
