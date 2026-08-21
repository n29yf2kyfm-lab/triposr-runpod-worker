#!/usr/bin/env python3
"""rear_survey.py — measure the rear zone BEFORE any cut.

Answers, from geometry only (never a material name, never a face normal --
CLAUDE.md: `interior` holds 45% of exterior panel faces, and 46% of normals in
the lamp band are flipped):

  1. where each named component actually sits (bbox + face centres)
  2. NESTED SURFACES: rays fired from +X through the tail, counting how many
     distinct surface crossings each ray makes and which mesh owns them.
     This is the "hidden melt underneath" measurement and it is the number
     Gate 3 v6 reported as 1.34% against its predecessor's 24.33%.
  3. SURFACE QUALITY of the hatch/bumper skins: for each face centre, the
     residual to a local quadratic fit of its neighbourhood (the physical
     definition of panel waviness), plus normal dispersion.

Run: python3 rear_survey.py <glb> <out.json>
"""
import json, sys
import numpy as np, trimesh
from scipy.spatial import cKDTree

GLB, OUT = sys.argv[1], sys.argv[2]
sc = trimesh.load(GLB, force="scene", process=False)
G = dict(sc.geometry)
allv = np.vstack([g.vertices for g in G.values()])
XMIN, XMAX = float(allv[:,0].min()), float(allv[:,0].max())
YMIN, YMAX = float(allv[:,1].min()), float(allv[:,1].max())
L = XMAX - XMIN
rep = {"L": L, "XMIN": XMIN, "XMAX": XMAX, "YMIN": YMIN, "YMAX": YMAX, "tail_at": "+X"}

# ---------- 1. component footprints ----------
comp = {}
for n, g in G.items():
    fc = g.triangles_center
    comp[n] = {"nf": int(len(g.faces)),
               "x": [round(float(fc[:,0].min()),4), round(float(fc[:,0].max()),4)],
               "y": [round(float(fc[:,1].min()),4), round(float(fc[:,1].max()),4)],
               "z": [round(float(fc[:,2].min()),4), round(float(fc[:,2].max()),4)],
               "area": round(float(g.area),5)}
    # how much of this mesh lies in the rear 20% of the car
    m = fc[:,0] > XMAX - 0.20*L
    comp[n]["frac_in_rear20"] = round(float(m.mean()),4)
    comp[n]["faces_in_rear20"] = int(m.sum())
rep["components"] = comp

# ---------- 2. nested-surface ray count from +X ----------
names = list(G.keys())
tris, owner = [], []
for i, n in enumerate(names):
    g = G[n]
    tris.append(g.triangles); owner.append(np.full(len(g.faces), i))
tris = np.vstack(tris); owner = np.concatenate(owner)
big = trimesh.Trimesh(vertices=tris.reshape(-1,3),
                      faces=np.arange(len(tris)*3).reshape(-1,3), process=False)
inter = trimesh.ray.ray_triangle.RayMeshIntersector(big)

def ray_grid(ny=44, nz=44, ylo=0.30, yhi=0.98, zspan=0.90):
    ys = np.linspace(YMIN + ylo*(YMAX-YMIN), YMIN + yhi*(YMAX-YMIN), ny)
    zs = np.linspace(-zspan, zspan, nz)
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    o = np.stack([np.full(Y.size, XMAX + 0.5), Y.ravel(), Z.ravel()], 1)
    d = np.tile(np.array([-1.0, 0, 0]), (len(o), 1))
    return o, d, ys, zs

o, d, ys, zs = ray_grid()
loc, idx_ray, idx_tri = inter.intersects_location(o, d, multiple_hits=True)
rep["ray_probe"] = {"n_rays": int(len(o)), "n_hits": int(len(loc))}
# per ray: sorted crossings, and how many lie within 120mm behind the FIRST
per = {}
for r, t, p in zip(idx_ray, idx_tri, loc):
    per.setdefault(int(r), []).append((float(p[0]), int(owner[t])))
nested_counts, first_owner, nested_within = [], [], []
NEST_D = 0.120
for r, hits in per.items():
    hits.sort(key=lambda h: -h[0])          # from +X inward
    xs = np.array([h[0] for h in hits])
    # collapse near-duplicate crossings (a shell's two skins <1mm apart)
    keep = [0]
    for i in range(1, len(xs)):
        if xs[keep[-1]] - xs[i] > 0.002: keep.append(i)
    xs2 = xs[keep]; own2 = [hits[i][1] for i in keep]
    nested_counts.append(len(xs2)); first_owner.append(own2[0])
    nested_within.append(int(((xs2[0] - xs2[1:]) < NEST_D).sum()))
nested_counts = np.array(nested_counts); nested_within = np.array(nested_within)
rep["nested"] = {
  "rays_hitting": int(len(nested_counts)),
  "mean_crossings": round(float(nested_counts.mean()),3),
  "pct_rays_with_second_surface_within_120mm": round(float((nested_within>0).mean()*100),3),
  "pct_rays_with_2plus_within_120mm": round(float((nested_within>1).mean()*100),3),
  "first_owner_hist": {names[i]: int((np.array(first_owner)==i).sum()) for i in range(len(names))
                       if (np.array(first_owner)==i).sum()},
}

# ---------- 3. surface quality of named skins ----------
def waviness(g, sample=6000, k=24):
    fc = g.triangles_center
    if len(fc) < 200: return None
    rng = np.random.default_rng(0)
    sel = rng.choice(len(fc), min(sample, len(fc)), replace=False)
    tree = cKDTree(fc)
    res = []
    for i in sel:
        dd, nb = tree.query(fc[i], k=min(k, len(fc)))
        P = fc[nb]
        c = P.mean(0); Q = P - c
        # local frame from PCA; fit quadratic height over the two in-plane axes
        u, s, vt = np.linalg.svd(Q, full_matrices=False)
        e1, e2, nrm = vt[0], vt[1], vt[2]
        a, b, h = Q@e1, Q@e2, Q@nrm
        A = np.stack([a*a, a*b, b*b, a, b, np.ones_like(a)], 1)
        try: coef, *_ = np.linalg.lstsq(A, h, rcond=None)
        except Exception: continue
        res.append(float(np.sqrt(np.mean((A@coef - h)**2))))
    res = np.array(res)
    # normal dispersion between adjacent faces
    fn = g.face_normals[sel]
    dd, nb = cKDTree(fc).query(fc[sel], k=min(8, len(fc)))
    ang = np.degrees(np.arccos(np.clip(np.einsum('ij,ikj->ik', fn, g.face_normals[nb]), -1, 1)))
    return {"n_sampled": int(len(res)),
            "wav_rms_mm": round(float(res.mean()*1000),4),
            "wav_p95_mm": round(float(np.percentile(res,95)*1000),4),
            "wav_p99_mm": round(float(np.percentile(res,99)*1000),4),
            "neighbour_normal_mean_deg": round(float(ang[:,1:].mean()),3),
            "neighbour_normal_p95_deg": round(float(np.percentile(ang[:,1:],95)),3)}

rep["surface_quality"] = {}
for n in ("Rear_Hatch","Rear_Bumper","Rear_Quarter_L","Rear_Quarter_R","Rear_Valance","carpaint","Rear_Glass"):
    if n in G: rep["surface_quality"][n] = waviness(G[n])

json.dump(rep, open(OUT,"w"), indent=1)
print(json.dumps({k:rep[k] for k in ("L","XMIN","XMAX","YMIN","YMAX","ray_probe","nested","surface_quality")}, indent=1))
