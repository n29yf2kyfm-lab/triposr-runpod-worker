#!/usr/bin/env python3
"""strip.py -- GATE 3 v7 step 1: REMOVE the corrupted front fascia.

Nothing is built here.  The output is the car with a hole in the front, and the
render of that hole is the single most important artefact in this gate: it is
what proves the rebuild replaced the melt rather than being laid over it.

WHY REMOVAL IS MANDATORY, not a preference.  The melt's own surface sits up to
27 mm IN FRONT of the fitted skin plane at the bottom of the grille band, so the
depth available for anything built OVER the shell is 18 mm mid-band and NEGATIVE
at the bottom.  A recess cannot be built into negative depth.

THE BEST-NAMED NODES ARE THE MELT.  `Headlamp_L`, `Headlamp_R` and
`Bumper_Front_Trim` are deleted ENTIRELY, not cut, because they are original
melted geometry that Gate 7+8's material rebind relabelled with clean semantic
names.  Measured, on this file:
  * Headlamp_L is 759 faces spanning z -0.639..-0.410 (229 mm) while Headlamp_R
    is 441 faces spanning z +0.065..+0.780 (715 mm).  A symmetric pair of
    headlamps does not differ by 3.1x in width and 1.7x in face count.
  * Headlamp_L sits 204..487 mm BEHIND the nose plane -- inside the engine bay.
  * Bumper_Front_Trim's frontmost footprint is 19,708 shredded cells scattered
    across the lower grille band, not a coherent part.
A node whose NAME is right and whose GEOMETRY is melt is more dangerous than an
unnamed one, because it passes a hierarchy check while failing the gate.

THE CUT IS ADAPTIVE IN DEPTH AND FOLLOWS THE CAR'S OWN BONNET EDGE ON TOP.
Depth: cut from the nose plane back to (local frontmost surface + 60 mm), floored
at 120 mm and capped at 300 mm, using the measured depth map -- a fixed-depth box
either leaves folds standing at the top or eats the underbody at the bottom.
Top: the cut's upper boundary is the MEASURED bonnet leading edge y(z), so the
rebuilt lamp's top edge lands on this car's own shut line and no wing is cut.
The lamp tips of a real Mk8 rise ABOVE the bonnet edge at the corners; that is
NOT reproduced here, because reproducing it means cutting into the wing, which is
the "parts laid over broken original" failure this gate exists to avoid.  It is
recorded as NOT BUILT with that reason rather than approximated.
Sides: each side is cut to ITS OWN fascia edge less a 12 mm flange, so no melt is
left standing inboard of the new parts on the wider side.  The car's front is
90-108 mm wider on +z than on -z at every height; that is the mesh's asymmetry,
not a choice.

DELETING FACES MOVES NOTHING, so this operation cannot dent a panel or tear a
seam the way a vertex pull can.  Authored vertex normals are captured before the
cut and written back after it: trimesh recomputes and discards authored shading
the moment `.faces` is assigned (Gate 6 paid for that one).

Run: python3 strip.py <car.glb> <ftex.npz> <plan.json> <out.glb> <report.json>
"""
import json
import os
import sys

import numpy as np
import trimesh
from scipy import ndimage

CAR, TEX, PLAN, OUT, REP = sys.argv[1:6]

d = np.load(TEX, allow_pickle=True)
D, ys, zs = d["D"], d["ys"], d["zs"]
RES, XNOSE = float(d["RES"]), float(d["XMIN"])
P = json.load(open(PLAN))
F = P["frame"]
ZC = F["z_centre"]
Y_DATUM = F["y_datum_bonnet_leading_edge"]
Y_LOW = F["y_bumper_lowest"]

DELETE_WHOLE = ["Headlamp_L", "Headlamp_R", "Bumper_Front_Trim"]
FLANGE = 0.012
Y_CUT_LO = Y_LOW - 0.004
DEPTH_MARGIN, DEPTH_MIN, DEPTH_MAX = 0.060, 0.120, 0.300

SIL = np.isfinite(D)

# ------------------------------------------------ upper boundary: bonnet edge
def bonnet_edge(zt, thr=1.3, half=0.030):
    ci = int(round((zt - zs[0]) / RES))
    k = int(half / RES)
    sl = slice(max(0, ci - k), min(len(zs), ci + k + 1))
    with np.errstate(all="ignore"):
        c = np.nanmin(np.where(SIL[:, sl], D[:, sl], np.nan), axis=1)
    ok = np.isfinite(c)
    if ok.sum() < 30:
        return np.nan
    idx = np.arange(len(ys))
    cf = ndimage.uniform_filter1d(np.interp(idx, idx[ok], c[ok]), 11)
    g = np.gradient(cf, RES)
    m = (ys < 1.02) & (ys > 0.60) & (g < thr)
    i = np.nonzero(m)[0]
    return float(ys[i[-1]]) if len(i) else np.nan


zt_s = np.arange(-0.90, 0.9001, 0.02)
be = np.array([bonnet_edge(z) for z in zt_s])
good = np.isfinite(be)
be = np.interp(zt_s, zt_s[good], be[good])
be = ndimage.uniform_filter1d(be, 5)
# never cut above the datum by more than 60 mm, never below it by more than 40
be = np.clip(be, Y_DATUM - 0.040, Y_DATUM + 0.060)
Y_TOP = lambda z: np.interp(z, zt_s, be)

# ------------------------------------------------ lateral boundary per side
zneg, zpos = {}, {}
ycent = np.arange(Y_CUT_LO, Y_DATUM + 0.061, 0.010)
for yy in ycent:
    m = SIL & ((ys > yy - 0.020) & (ys < yy + 0.020))[:, None] & (D < 0.42)
    cnt = m.sum(0)
    i = np.nonzero(cnt >= 4)[0]
    zneg[yy] = float(zs[i.min()]) if len(i) else np.nan
    zpos[yy] = float(zs[i.max()]) if len(i) else np.nan
yk = np.array(sorted(zneg))
zn = np.array([zneg[y] for y in yk])
zp = np.array([zpos[y] for y in yk])
for arr in (zn, zp):
    g = np.isfinite(arr)
    arr[:] = np.interp(yk, yk[g], arr[g])
zn = ndimage.uniform_filter1d(zn, 5) + FLANGE
zp = ndimage.uniform_filter1d(zp, 5) - FLANGE

# ------------------------------------------------ adaptive depth
Dmax = ndimage.grey_dilation(np.where(SIL, D, 0.0), size=(9, 9))
DCUT = np.clip(Dmax + DEPTH_MARGIN, DEPTH_MIN, DEPTH_MAX)
DCUT = ndimage.uniform_filter(DCUT, 7)


def cut_depth(Y, Z):
    r = np.clip(np.rint((Y - ys[0]) / RES).astype(int), 0, len(ys) - 1)
    c = np.clip(np.rint((Z - zs[0]) / RES).astype(int), 0, len(zs) - 1)
    return DCUT[r, c]


# ================================================================== execute
sc = trimesh.load(CAR, force="scene", process=False)
R = {"deleted_nodes": {}, "cut_faces": {}, "kept": {}, "params": {
     "flange_m": FLANGE, "y_cut_lo": Y_CUT_LO,
     "depth_margin_m": DEPTH_MARGIN, "depth_min_m": DEPTH_MIN,
     "depth_max_m": DEPTH_MAX,
     "bonnet_edge_y_at_z": {str(round(z, 2)): round(float(Y_TOP(z)), 4)
                            for z in (-0.6, -0.3, 0.0, 0.3, 0.6)}}}

before = {n: int(len(sc.geometry[sc.graph[n][1]].faces))
          for n in sc.graph.nodes_geometry}

for n in DELETE_WHOLE:
    if n in sc.graph.nodes_geometry:
        R["deleted_nodes"][n] = before[n]
        sc.delete_geometry(sc.graph[n][1])
        print(f"DELETED WHOLE NODE {n}  ({before[n]} faces)")

total = 0
for node in list(sc.graph.nodes_geometry):
    T, gname = sc.graph[node]
    g = sc.geometry[gname]
    # authored normals, captured BEFORE .faces is touched
    vn = np.asarray(g.vertex_normals, float).copy() \
        if g.vertex_normals is not None else None
    v = trimesh.transform_points(np.asarray(g.vertices, float), T)
    c = v[np.asarray(g.faces)].mean(1)

    kill = (c[:, 1] > Y_CUT_LO) & (c[:, 1] < Y_TOP(c[:, 2]))
    kill &= (c[:, 2] > np.interp(c[:, 1], yk, zn)) & \
            (c[:, 2] < np.interp(c[:, 1], yk, zp))
    dep = c[:, 0] - XNOSE
    kill &= (dep >= -0.001) & (dep < cut_depth(c[:, 1], c[:, 2]))
    nk = int(kill.sum())
    if nk:
        g.update_faces(~kill)
        if vn is not None and len(vn) == len(g.vertices):
            g.vertex_normals = vn
        R["cut_faces"][node] = nk
        total += nk
    R["kept"][node] = int(len(g.faces))
    if nk:
        print(f"CUT {node:22s} {nk:7d} of {before[node]:7d}  -> {len(g.faces)} kept")

R["cut_total"] = total
R["deleted_total"] = int(sum(R["deleted_nodes"].values()))
R["faces_before"] = int(sum(before.values()))
R["faces_after"] = int(sum(R["kept"].values()))
print(f"\nDELETED NODES {R['deleted_total']} faces   CUT {total} faces   "
      f"{R['faces_before']} -> {R['faces_after']}")

# `Scene.delete_geometry` drops the mesh but LEAVES THE NODE in the graph, and
# the Khronos validator flags each one as NODE_EMPTY.  The base file has none of
# these, so leaving them would be a defect this gate introduced.  The scene is
# rebuilt from the surviving geometry nodes instead.  Measured: 3 NODE_EMPTY
# hints before this, 0 after.
out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gname = sc.graph[node]
    if gname not in sc.geometry:
        continue
    g = sc.geometry[gname]
    if len(g.faces) == 0:
        R.setdefault("dropped_empty_nodes", []).append(node)
        continue
    if gname not in out.geometry:
        out.add_geometry(g, geom_name=gname, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gname)
sc = out
sc.export(OUT)
R["out_bytes"] = os.path.getsize(OUT)
json.dump(R, open(REP, "w"), indent=1)
print(f"STRIP_DONE {OUT} ({R['out_bytes']} bytes)")
