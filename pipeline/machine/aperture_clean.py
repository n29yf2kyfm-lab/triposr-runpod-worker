#!/usr/bin/env python3
"""aperture_clean.py — remove body MELT TEETH from the glazing apertures.

Isolated by component bisection on 2026-08-18: with every glazing, frit,
backstop and interior node hidden, the ragged comb fringe across the side
windows is STILL PRESENT, so it is the carpaint shell's own aperture edge
— thin sliver triangles hanging into the window opening, measured up to
412mm below the DLO top rail. It is the dominant visual defect on the car
and it is NOT a glazing defect; Stage 2's de-staircasing could not touch
it.

Selection is deliberately narrow so pillars cannot be eaten:
  * the face must lie inside the REAL pane footprint polygon (the pane's
    own boundary loop projected to x/y, winding-number test) — not its
    convex hull, which would swallow the B-pillar
  * ALL THREE vertices must be inside (a face straddling the rim stays)
  * the face must be a SLIVER (aspect ratio > ASPECT) — pillars and door
    frames are ordinary triangles and are measurably spared; the script
    prints the pillar-band aspect distribution so the guard is checked,
    not assumed
  * the face must not be part of a large connected patch (>MAXPATCH
    faces), so a genuine panel that happens to sit inside the opening
    survives

Run: python3 aperture_clean.py <in.glb> <out.glb>
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

INP, OUT = sys.argv[1], sys.argv[2]
FOOT = sys.argv[3] if len(sys.argv) > 3 else INP.replace(".glb", "_nodes.json")
ASPECT = 6.0     # secondary filter only — the FOOTPRINT does the work
MAXPATCH = 400
PANES = ("Glass_Side_FR", "Glass_Side_RR", "Glass_Side_FL", "Glass_Side_RL",
         "Glass_Windscreen", "Glass_Rear_Screen")


def boundary_loop_xy(mesh, axis=(0, 1)):
    """Longest boundary loop of a mesh, projected to two axes."""
    eu, cnt = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    b = eu[cnt == 1]
    if not len(b):
        return None
    adj = {}
    for a, c in b:
        adj.setdefault(int(a), []).append(int(c))
        adj.setdefault(int(c), []).append(int(a))
    best, seen = None, set()
    for start in adj:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                break
            n = nxt[0]
            loop.append(n); seen.add(n); prev, cur = cur, n
        if best is None or len(loop) > len(best):
            best = loop
    if best is None or len(best) < 8:
        return None
    return mesh.vertices[best][:, list(axis)]


def inside_poly(pts, poly):
    """Vectorised even-odd ray cast."""
    x, y = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    for i in range(len(poly)):
        cond = ((y1[i] > y) != (y2[i] > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2[i] - x1[i]) * (y - y1[i]) / (y2[i] - y1[i] + 1e-12) + x1[i]
        inside ^= cond & (x < xint)
    return inside


sc = trimesh.load(INP, force="scene")
cp = sc.geometry["carpaint"]
tri = cp.triangles
cent = cp.triangles_center
a = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
b_ = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
c_ = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
s = (a + b_ + c_) / 2
area = np.sqrt(np.maximum(s * (s - a) * (s - b_) * (s - c_), 1e-20))
aspect = np.maximum.reduce([a, b_, c_]) / np.maximum(2 * area / np.maximum(s, 1e-9), 1e-9)

# GUARD CHECK: pillar-band aspect distribution, printed so the assumption
# that pillars are ordinary triangles is verified rather than trusted
pill = (cent[:, 1] > 0.95) & (cent[:, 1] < 1.25) & (np.abs(cent[:, 2]) > 0.55) & \
       (cent[:, 0] > -0.30) & (cent[:, 0] < -0.15)
if pill.sum():
    print(f"pillar-band guard: {pill.sum()} faces, aspect median "
          f"{np.median(aspect[pill]):.2f}, p95 {np.percentile(aspect[pill], 95):.2f}, "
          f"share above cut {100 * (aspect[pill] > ASPECT).mean():.1f}%")

faces = cp.faces
vi = cp.vertices
kill = np.zeros(len(faces), bool)
report = {}
foot = json.load(open(FOOT)).get("_footprints", {})
if not foot:
    raise SystemExit(f"no _footprints in {FOOT} — rebuild glass with the current glass_nodes.py")
for pane, loop in foot.items():
    P = np.asarray(loop, float)
    axis = [0, 1] if "Side" in pane else [2, 1]
    poly = P[:, axis]
    v_in = inside_poly(vi[:, axis], poly)
    allin = v_in[faces].all(1)
    if "Side" in pane:
        zside = np.sign(P[:, 2].mean())
        allin &= (np.sign(cent[:, 2]) == zside) & (np.abs(cent[:, 2]) > 0.45)
        # depth band: only faces near the pane surface can be teeth
        zmid = float(np.median(P[:, 2]))
        allin &= np.abs(cent[:, 2] - zmid) < 0.10
    else:
        xmid = float(np.median(P[:, 0]))
        allin &= np.abs(cent[:, 0] - xmid) < 0.14
    sel = allin & (aspect > ASPECT)
    kill |= sel
    report[pane] = {"faces_inside_footprint": int(allin.sum()),
                    "slivers_selected": int(sel.sum())}
    print(f"  {pane}: {allin.sum()} faces inside TRUE footprint, {sel.sum()} selected")

# patch-size guard: never delete a large connected region
idx = np.where(kill)[0]
if len(idx):
    ff = faces[idx]
    u = np.unique(ff)
    remap = {int(x): i for i, x in enumerate(u)}
    e = np.vstack([ff[:, [0, 1]], ff[:, [1, 2]], ff[:, [2, 0]]])
    gmat = coo_matrix((np.ones(len(e)),
                       ([remap[int(x)] for x in e[:, 0]], [remap[int(x)] for x in e[:, 1]])),
                      shape=(len(u), len(u)))
    _, lab = connected_components(gmat, directed=False)
    flab = lab[[remap[int(x)] for x in ff[:, 0]]]
    sizes = np.bincount(flab)
    big = np.where(sizes > MAXPATCH)[0]
    if len(big):
        spared = np.isin(flab, big)
        kill[idx[spared]] = False
        print(f"patch guard: spared {spared.sum()} faces in {len(big)} large patches")

before = len(cp.faces)
cp.update_faces(~kill)
cp.remove_unreferenced_vertices()
print(f"carpaint {before} -> {len(cp.faces)} faces ({kill.sum()} melt teeth removed)")

out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m.get("name") for m in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
report["_totals"] = {"carpaint_before": int(before), "carpaint_after": int(len(cp.faces)),
                     "removed": int(kill.sum()), "aspect_cut": ASPECT,
                     "max_patch": MAXPATCH}
json.dump(report, open(OUT.replace(".glb", "_aperture.json"), "w"), indent=1)
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
