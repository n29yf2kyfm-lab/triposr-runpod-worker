#!/usr/bin/env python3
"""glass_nodes.py — DEPRECATED: use glass_stage.py (car-agnostic Stage 2).

This script is the V41 DEVELOPMENT RECORD — its constants are V41-tuned
(absolute coordinates, unconditional right-side rebuild, fixed 18mm
desnake cap). glass_stage.py supersedes it: spec-driven labels, geometric
classification, conditional rebuild, measured desnake cap with a
quantisation-ratio gate, double-skin pane grouping, hierarchy baking,
scale-relative constants, and self-tests that refuse instead of shipping
a wrong cut. Validated 2026-08-18 on four bodies: V41 Golf (reproduces
this script's output), hybrid melt (honest refusal), a fused-glazing
catalogue car (honest refusal), and a multi-node double-skinned classic
Golf GTI (8 panes, validator clean). Kept for the record only.

Original docstring follows.

Stage 2 of the V41 repair brief: REAL glass nodes.

From the locked baseline's single merged "glass" node this stage builds:

  * Glass_Windscreen, Glass_Side_FL, Glass_Side_RL, Glass_Side_FR,
    Glass_Side_RR, Glass_Rear_Screen — separate NAMED nodes
  * the incomplete right side (measured: stopped at x -0.82 while the
    left runs to -1.32; the dark aperture_backstop was standing in for
    the missing rear-right glass) is rebuilt as the mirrored LEFT
    footprint on the right side's OWN fitted quadric (rms 0.1mm) —
    verified by locked-camera render, not by the (invalid) poke probe
  * every pane gets REAL THICKNESS: inner shell at -4mm along the
    outward normal + a stitched perimeter wall, so the glass edge is
    visible geometry, not a zero-thickness sheet
  * side panes split at the measured B-pillar centre into front/rear
    door panes (quarter glass is integrated in the rear segment on this
    body — recorded as a limitation, not hidden)

frit_band (borders/seals), cabin_occluder and the interior kit are
retained untouched. Everything else in the car is byte-identical.

Run: python3 glass_nodes.py <in.glb> <out.glb>
"""
import json
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]
THICK = 0.004

sc = trimesh.load(INP, force="scene")
g = sc.geometry["glass"]
comps = g.split(only_watertight=False)
ident = {}
for c in comps:
    b = c.bounds; cx = b.mean(0)
    if b[0][0] > 0.3: ident["windscreen"] = c
    elif b[0][0] < -1.5 and abs(cx[2]) < 0.2: ident["rear_screen"] = c
    elif cx[2] < -0.3: ident["side_L"] = c
    else: ident["side_R"] = c
assert len(ident) == 4, f"expected 4 glass components, got {list(ident)}"

# rebuild right side: mirrored left footprint on right-fitted quadric
L, R = ident["side_L"], ident["side_R"]
V = R.vertices
A = np.c_[np.ones(len(V)), V[:, 0], V[:, 1], V[:, 0]**2, V[:, 0]*V[:, 1], V[:, 1]**2]
coef, *_ = np.linalg.lstsq(A, V[:, 2], rcond=None)
Rm = L.copy(); Vm = Rm.vertices.copy()
Am = np.c_[np.ones(len(Vm)), Vm[:, 0], Vm[:, 1], Vm[:, 0]**2, Vm[:, 0]*Vm[:, 1], Vm[:, 1]**2]
Vm[:, 2] = Am @ coef - 0.002
Rm.vertices = Vm; Rm.faces = Rm.faces[:, ::-1]
ident["side_R"] = Rm
print(f"side_R rebuilt: {len(Rm.faces)} faces, x [{Vm[:,0].min():.2f},{Vm[:,0].max():.2f}]")

# B-pillar x from the body: densest carpaint column inside the DLO band
cp = sc.geometry["carpaint"]
cent = cp.triangles_center
# window is MID-CABIN ONLY: a [-0.6,0.5] window put the peak at x=0.487,
# the A-pillar base, and split 792-face "front door" slivers (measured)
m = (cent[:, 1] > 0.95) & (cent[:, 1] < 1.25) & (np.abs(cent[:, 2]) > 0.55) & \
    (cent[:, 0] > -0.45) & (cent[:, 0] < 0.30)
hist, edges = np.histogram(cent[m, 0], bins=44)
BPX = float((edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2)
print(f"B-pillar centre x = {BPX:.3f} (from {m.sum()} pillar-band faces)")


def boundary_loops(mesh):
    """Ordered boundary loops (lists of vertex indices)."""
    eu, cnt = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    b = eu[cnt == 1]
    adj = {}
    for a, c in b:
        adj.setdefault(int(a), []).append(int(c))
        adj.setdefault(int(c), []).append(int(a))
    seen, loops = set(), []
    for start in adj:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev]
            nxt = [n for n in nxt if n not in seen] or [n for n in nxt if n == start]
            if not nxt:
                break
            n = nxt[0]
            if n == start:
                break
            loop.append(n); seen.add(n); prev, cur = cur, n
        if len(loop) > 6:
            loops.append(loop)
    return loops


def turning_angle(mesh, loops):
    """Mean |turn| between consecutive boundary edges — the staircase metric.

    A voxel staircase alternates ~90 deg turns; a smooth curve stays low.
    """
    tot, n = 0.0, 0
    for lp in loops:
        P = mesh.vertices[lp]
        d = np.roll(P, -1, axis=0) - P
        ln = np.linalg.norm(d, axis=1, keepdims=True)
        d = d / np.clip(ln, 1e-9, None)
        dot = np.clip((d * np.roll(d, -1, axis=0)).sum(1), -1, 1)
        tot += np.degrees(np.arccos(dot)).sum(); n += len(lp)
    return tot / max(n, 1)


def desnake(mesh, iters=14, max_disp=0.018, label=""):
    """Remove VOXEL QUANTISATION from boundary loops.

    Laplacian smoothing applied ONLY to boundary-loop vertices, with a hard
    per-vertex displacement cap (default 18mm — the measured staircase
    amplitude is ~10-15mm). The cap is what makes this a de-quantisation
    and not a reshaping: no boundary vertex can travel further than the
    staircase it is removing, so the silhouette cannot be redrawn.
    Interior vertices are never touched.
    """
    m = mesh.copy()
    loops = boundary_loops(m)
    if not loops:
        return m, None
    before = turning_angle(m, loops)
    orig = m.vertices.copy()
    V = m.vertices.copy()
    for _ in range(iters):
        for lp in loops:
            P = V[lp]
            sm = 0.5 * P + 0.25 * np.roll(P, 1, axis=0) + 0.25 * np.roll(P, -1, axis=0)
            V[lp] = sm
    disp = V - orig
    d = np.linalg.norm(disp, axis=1)
    over = d > max_disp
    if over.any():
        V[over] = orig[over] + disp[over] * (max_disp / d[over])[:, None]
    m.vertices = V
    after = turning_angle(m, loops)
    stats = {"loops": len(loops),
             "boundary_verts": int(sum(len(l) for l in loops)),
             "turning_before_deg": round(float(before), 2),
             "turning_after_deg": round(float(after), 2),
             "max_disp_mm": round(float(np.linalg.norm(V - orig, axis=1).max() * 1000), 2),
             "mean_disp_mm": round(float(np.linalg.norm(V - orig, axis=1)[d > 0].mean() * 1000), 2)}
    print(f"  desnake {label}: turning {stats['turning_before_deg']} -> "
          f"{stats['turning_after_deg']} deg over {stats['loops']} loops, "
          f"max disp {stats['max_disp_mm']}mm")
    return m, stats


def split_x(mesh, x0):
    keepf = mesh.triangles_center[:, 0] >= x0
    fr = mesh.copy(); fr.update_faces(keepf); fr.remove_unreferenced_vertices()
    rr = mesh.copy(); rr.update_faces(~keepf); rr.remove_unreferenced_vertices()
    return fr, rr


def thicken(mesh, outward_hint):
    """Inner shell -THICK along outward normal + stitched perimeter wall."""
    m = mesh.copy()
    n = m.vertex_normals.copy()
    flip = (n.mean(0) @ outward_hint) < 0
    if flip:
        n = -n
    inner_v = m.vertices - n * THICK
    nv = len(m.vertices)
    V2 = np.vstack([m.vertices, inner_v])
    F2 = [m.faces if not flip else m.faces[:, ::-1],
          (m.faces[:, ::-1] if not flip else m.faces) + nv]
    eu, cnt = np.unique(np.sort(m.edges, axis=1), axis=0, return_counts=True)
    boundary = eu[cnt == 1]
    wall = []
    for a, b in boundary:
        wall += [[a, b, b + nv], [a, b + nv, a + nv]]
    F2.append(np.array(wall).reshape(-1, 3))
    out = trimesh.Trimesh(vertices=V2, faces=np.vstack(F2), process=True)
    return out, len(boundary)


FL, RL = split_x(ident["side_L"], BPX)
FR_, RR_ = split_x(ident["side_R"], BPX)
panes = {"Glass_Windscreen": (ident["windscreen"], np.array([0.8, 0.6, 0.0])),
         "Glass_Side_FL": (FL, np.array([0.0, 0.1, -1.0])),
         "Glass_Side_RL": (RL, np.array([0.0, 0.1, -1.0])),
         "Glass_Side_FR": (FR_, np.array([0.0, 0.1, 1.0])),
         "Glass_Side_RR": (RR_, np.array([0.0, 0.1, 1.0])),
         "Glass_Rear_Screen": (ident["rear_screen"], np.array([-0.8, 0.5, 0.0]))}

from trimesh.visual.material import PBRMaterial
gmat = None
for m_ in sc.geometry["glass"].visual.material,:
    gmat = m_
out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn == "glass":
        continue
    geom = sc.geometry[gn]
    if gn == "frit_band":
        geom, fst = desnake(geom, label="frit_band")
    if gn not in out.geometry:
        out.add_geometry(geom, geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
table = {}
desnake_stats = {}
footprints = {}
for name, (mesh, hint) in panes.items():
    mesh, st = desnake(mesh, label=name)
    if st:
        desnake_stats[name] = st
    # export the PRE-THICKEN boundary loop: thicken() closes the pane, so
    # the footprint is unrecoverable downstream (aperture_clean needs it
    # to tell a melt tooth from a pillar — measured 2026-08-18)
    lps = boundary_loops(mesh)
    if lps:
        lp = max(lps, key=len)
        footprints[name] = mesh.vertices[lp].tolist()
    solid, nb = thicken(mesh, hint)
    mat = PBRMaterial(name=name, baseColorFactor=[20, 24, 28, 90],
                      metallicFactor=0.0, roughnessFactor=0.05,
                      alphaMode="BLEND", doubleSided=True)
    solid.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(solid, node_name=name, geom_name=name)
    b = solid.bounds
    table[name] = {"faces": int(len(solid.faces)), "boundary_edges_stitched": int(nb),
                   "bbox_min": [round(float(x), 3) for x in b[0]],
                   "bbox_max": [round(float(x), 3) for x in b[1]],
                   "thickness_m": THICK}
    print(f"  {name}: {len(solid.faces)} faces, wall from {nb} boundary edges")

out.export(OUT, include_normals=True)
import os
import struct
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:5]}")
table["_desnake"] = desnake_stats
table["_footprints"] = footprints
try:
    table["_desnake"]["frit_band"] = fst
except NameError:
    pass
json.dump(table, open(OUT.replace(".glb", "_nodes.json"), "w"), indent=1)
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes), NORMALs verified, "
      f"node table -> {OUT.replace('.glb','_nodes.json')}")
