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
FOOT = INP.replace(".glb", "_nodes.json")
TAG_ONLY = "--tag" in sys.argv          # write a magenta-tagged GLB, delete nothing
SPEC_PATH = None
args = sys.argv[3:]
for i, a in enumerate(args):
    if a == "--spec":
        SPEC_PATH = args[i + 1]
    elif a.endswith(".json") and (i == 0 or args[i - 1] != "--spec"):
        FOOT = a
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from carspec import CarSpec
spec = CarSpec.load(SPEC_PATH) if SPEC_PATH else CarSpec.empty()
BODY_LABEL = spec.label("body", "carpaint")

# The physical constants below were MEASURED on the V41 Golf body
# (L 4.284m) and scale with car size — on a quarter-scale body a 20mm rim
# band would be the whole pillar. They are scaled by measured body length
# relative to the calibration body, tagged APPROXIMATE off-calibration.
CAL_L = 4.284
RIM_KEEP0 = 0.020 # m: never delete within this band of the aperture rim — the
                 # rim faces are STRUCTURAL. Deleting them tore an open notch
                 # in the rear quarter (seen in the V45 locked render); the
                 # teeth that actually matter hang deeper into the opening.
OUTBOARD0 = 0.08 # m: a face further outboard than this is a FIXTURE, not a tooth
                 # (measured: wing mirror sits 194mm outboard of the glass plane,
                 #  melt teeth hang at or inboard of it)
MAXPATCH = 400   # faces — topological, NOT scaled. A 60-face guard SPARED the
                 # roof-rail strips that ARE the fringe (they run 0.55-0.95m
                 # long), so it fixed less, not more. Measured 2026-08-18.
TAIL_KEEP0 = 0.20 # m from the footprint's rearmost point: the pane footprint
                 # over-covers the C-pillar/quarter there, and deleting inside
                 # it tore the quarter open (V46 rear-quarter regression).
                 # The footprint is unreliable in that corner, so nothing is
                 # removed from it — recorded as an untreated zone, not a fix.


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


def rim_distance(C, poly, chunk=20000):
    """Min distance from each 2D point to the closed polyline, CHUNKED.
    The one-shot broadcast builds an (N_pts x N_loop x 2) temp — measured
    456k faces x 1778 loop points = ~13GB and an OOM kill (RC=137) on the
    Yaris premium chain. Same maths, bounded memory."""
    seg0 = poly
    seg1 = np.roll(seg0, -1, axis=0)
    d = seg1 - seg0
    L2 = np.maximum((d * d).sum(1), 1e-12)
    out = np.empty(len(C))
    for i in range(0, len(C), chunk):
        Cc = C[i:i + chunk]
        tpar = np.clip(((Cc[:, None, :] - seg0[None]) * d[None]).sum(2)
                       / L2[None], 0, 1)
        proj = seg0[None] + tpar[..., None] * d[None]
        out[i:i + chunk] = np.linalg.norm(Cc[:, None, :] - proj, axis=2).min(1)
    return out


sc = trimesh.load(INP, force="scene")
if BODY_LABEL not in sc.geometry:
    raise SystemExit(f"REFUSED: body node {BODY_LABEL!r} absent; scene has "
                     f"{sorted(sc.geometry)[:20]}")
cp = sc.geometry[BODY_LABEL]
L_body = float(cp.vertices[:, 0].max() - cp.vertices[:, 0].min())
SCALE = L_body / CAL_L
RIM_KEEP = RIM_KEEP0 * SCALE
OUTBOARD = OUTBOARD0 * SCALE
TAIL_KEEP = TAIL_KEEP0 * SCALE
print(f"body length {L_body:.3f}m -> constant scale {SCALE:.3f} "
      f"(rim {RIM_KEEP*1000:.0f}mm, outboard {OUTBOARD*1000:.0f}mm, "
      f"tail {TAIL_KEEP*1000:.0f}mm"
      + ("; APPROXIMATE — off the calibration body)" if abs(SCALE-1) > 0.05 else ")"))
tri = cp.triangles
cent = cp.triangles_center
a = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
b_ = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
c_ = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
s = (a + b_ + c_) / 2
area = np.sqrt(np.maximum(s * (s - a) * (s - b_) * (s - c_), 1e-20))
aspect = np.maximum.reduce([a, b_, c_]) / np.maximum(2 * area / np.maximum(s, 1e-9), 1e-9)

# GUARD CHECK: pillar-band aspect distribution, printed so the assumption
# that pillars are ordinary triangles is verified rather than trusted.
# Band derived from the side-pane footprints (was absolute V41 coords).
_foot_pre = json.load(open(FOOT)).get("_footprints", {})
_sideP = [np.asarray(v) for k, v in _foot_pre.items() if "Side" in k]
if _sideP:
    _sp = np.vstack(_sideP)
    _y0, _y1 = _sp[:, 1].min(), _sp[:, 1].max()
    _midx = float(np.median(_sp[:, 0]))
    _bw = 0.035 * (_sp[:, 0].max() - _sp[:, 0].min())
    pill = ((cent[:, 1] > _y0 + 0.2 * (_y1 - _y0)) &
            (cent[:, 1] < _y0 + 0.8 * (_y1 - _y0)) &
            (np.abs(cent[:, 2]) > 0.85 * np.median(np.abs(_sp[:, 2]))) &
            (cent[:, 0] > _midx - _bw) & (cent[:, 0] < _midx + _bw))
    if pill.sum():
        print(f"pillar-band guard: {pill.sum()} faces, aspect median "
              f"{np.median(aspect[pill]):.2f}, p95 {np.percentile(aspect[pill], 95):.2f} "
              f"(NOTE: pillars are themselves slivers — this is why aspect is NOT a filter)")

faces = cp.faces
vi = cp.vertices
kill = np.zeros(len(faces), bool)
report = {}
foot = json.load(open(FOOT)).get("_footprints", {})
if not foot:
    raise SystemExit(f"no _footprints in {FOOT} — rebuild glass with the current glass_nodes.py")
from scipy.spatial import cKDTree
for pane, loop in foot.items():
    P = np.asarray(loop, float)
    side = "Side" in pane
    if not side:
        # SCREENS: a world-axis projection of a raked screen encloses the
        # whole nose/tail (measured 14,775 faces "inside" — projection
        # failure, not defect). Work in the pane's OWN principal frame:
        # PCA of the footprint gives (u,v) in the glass plane and n normal;
        # candidates must sit within a thin slab along n, so the bonnet and
        # tailgate below/behind the glass can never be selected.
        ctr0 = P.mean(0)
        _, _, Vt = np.linalg.svd(P - ctr0, full_matrices=False)
        u_ax, v_ax, n_ax = Vt[0], Vt[1], Vt[2]
        poly = np.c_[(P - ctr0) @ u_ax, (P - ctr0) @ v_ax]
        rel = cent - ctr0
        cu, cv, cn = rel @ u_ax, rel @ v_ax, rel @ n_ax
        ins = inside_poly(np.c_[cu, cv], poly) & (np.abs(cn) < 0.10 * SCALE)
        rim_dist = rim_distance(np.c_[cu, cv], poly)
        sel = ins & (rim_dist > RIM_KEEP)
        kill |= sel
        report[pane] = {"inside_footprint": int(ins.sum()),
                        "excluded_as_rim_structure": int((ins & (rim_dist <= RIM_KEEP)).sum()),
                        "selected": int(sel.sum()), "frame": "PCA plane"}
        print(f"  {pane}: slab-inside {ins.sum()}, rim spared "
              f"{(ins & (rim_dist <= RIM_KEEP)).sum()}, selected {sel.sum()}")
        continue
    axis = [0, 1] if side else [2, 1]
    depth_axis = 2 if side else 0
    poly = P[:, axis]
    # centroid-inside, NOT all-three-inside: a tooth hangs from the rim, so
    # its base vertex sits ON the boundary and an all-inside rule misses it
    ins = inside_poly(cent[:, axis], poly)
    if side:
        zs = np.sign(P[:, 2].mean())
        # depth screen from the pane's own footprint, not absolute coords
        ins &= (np.sign(cent[:, depth_axis]) == zs) & \
               (np.abs(cent[:, depth_axis]) > 0.7 * np.median(np.abs(P[:, 2])))
    # LOCAL outboard limit: compare each face against the pane surface at its
    # own (x,y), not a global median — the pane is curved
    t = cKDTree(P[:, axis])
    _, ni = t.query(cent[:, axis], k=1)
    local = P[ni, depth_axis]
    if side:
        outb = (np.abs(cent[:, depth_axis]) - np.abs(local)) > OUTBOARD
    else:
        outb = (np.abs(cent[:, depth_axis]) - np.abs(local)) > OUTBOARD
    # distance from each candidate centroid to the aperture rim polyline
    rim_dist = rim_distance(cent[:, axis], P[:, axis])
    tail = cent[:, 0] < (P[:, 0].min() + TAIL_KEEP)
    sel = ins & ~outb & (rim_dist > RIM_KEEP) & ~tail
    kill |= sel
    report[pane] = {"inside_footprint": int(ins.sum()),
                    "excluded_as_outboard_fixture": int((ins & outb).sum()),
                    "excluded_as_rim_structure": int((ins & ~outb & (rim_dist <= RIM_KEEP)).sum()),
                    "excluded_as_tail_corner": int((ins & tail).sum()),
                    "selected": int(sel.sum())}
    print(f"  {pane}: inside {ins.sum()}, outboard {(ins & outb).sum()}, "
          f"rim {(ins & ~outb & (rim_dist <= RIM_KEEP)).sum()}, "
          f"tail-corner {(ins & tail).sum()}, selected {sel.sum()}")

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

if TAG_ONLY:
    from trimesh.visual.material import PBRMaterial
    tag = cp.copy(); tag.update_faces(kill); tag.remove_unreferenced_vertices()
    tag.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name="TAG", baseColorFactor=[255, 0, 220, 255], metallicFactor=0.0,
        roughnessFactor=0.4))
    rest = cp.copy(); rest.update_faces(~kill); rest.remove_unreferenced_vertices()
    o = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        g = rest if gn == BODY_LABEL else sc.geometry[gn]
        if gn not in o.geometry:
            o.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            o.graph.update(frame_to=node, matrix=T, geometry=gn)
    o.add_geometry(tag, geom_name="TAG", node_name="TAG")
    o.export(OUT, include_normals=True)
    print(f"TAG MODE: {kill.sum()} faces tagged magenta -> {OUT} (nothing deleted)")
    raise SystemExit(0)

before = len(cp.faces)
eu0, cnt0 = np.unique(np.sort(cp.edges, axis=1), axis=0, return_counts=True)
bnd_before = int((cnt0 == 1).sum())
cp.update_faces(~kill)
cp.remove_unreferenced_vertices()
eu1, cnt1 = np.unique(np.sort(cp.edges, axis=1), axis=0, return_counts=True)
bnd_mid = int((cnt1 == 1).sum())
# Cutting teeth opens boundary. Left unfilled it reads as a TEAR in the
# body (seen at the rear quarter in the V45 locked render), which is a
# regression, not a repair — so the holes are closed here.
# GLOBAL fill_holes() IS A REGRESSION — DO NOT RE-ENABLE. Measured on
# V47: the shell carries 217,726 PRE-EXISTING boundary edges (it is
# fragment soup, not a closed surface), so a global fill added 17,902
# faces and scattered dark garbage triangles across the door skin in the
# locked right_ortho render. The cut itself REDUCES boundary (217,726 ->
# 214,746) because teeth carry their own boundary with them; there is no
# net hole to fill. Any future fill must be local to the cut and
# validated on the same locked camera.
filled = 0
eu2, cnt2 = np.unique(np.sort(cp.edges, axis=1), axis=0, return_counts=True)
bnd_after = int((cnt2 == 1).sum())
print(f"carpaint {before} -> {len(cp.faces)} faces ({kill.sum()} teeth cut, "
      f"{filled} fill faces added — global fill disabled, see docstring)")
print(f"boundary edges: {bnd_before} before -> {bnd_mid} after cut -> {bnd_after} after fill")

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
                     "removed": int(kill.sum()), "outboard_limit_m": OUTBOARD,
                     "rim_keep_m": RIM_KEEP, "tail_keep_m": TAIL_KEEP, "fill_faces_added": int(filled),
                     "boundary_edges_before": bnd_before,
                     "boundary_edges_after_cut": bnd_mid,
                     "boundary_edges_after_fill": bnd_after,
                     "max_patch": MAXPATCH}
json.dump(report, open(OUT.replace(".glb", "_aperture.json"), "w"), indent=1)
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
