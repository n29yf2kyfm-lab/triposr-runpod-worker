#!/usr/bin/env python3
"""verify_holes.py — did the cut open a hole? 15 directions, before vs after.

A ray that HIT the car before the cut and MISSES it afterwards is a hole, by
definition. Nothing else in this test is interpretation.

Directions: az 0 / +-22 / +-40 x el 0 / +-18, all relative to the rear axis
(+X on this file, established by render).

NEGATIVE CONTROL is mandatory here -- CLAUDE.md records two checks on this
programme that were EMPTY BY CONSTRUCTION and reported PASS forever. Run with
--selftest to delete a 90 mm disc of faces from the rebuilt tailgate and
confirm the probe reports it.

IT CAUGHT MY OWN BROKEN PROBE, which is the only reason this file is correct.
v1 asked `ray.intersects_any` -- "does this ray hit ANYTHING". A car has a
cabin, seats and an underbody behind every outer panel, so a ray fired through
a hole punched clean out of the tailgate still hits something and still counts
as a hit. The selftest returned a byte-identical result to the real run
(35 rays lost, 0.1577%) and that identity is what exposed it: a control that
cannot move is not a control.

The probe now measures the FIRST-HIT DEPTH. A hole is not "nothing is there",
it is "the outermost surface has receded", and that is what gets measured:
a ray counts as a hole if it hit before and misses now, or if its nearest
surface has moved away by more than TOL. TOL is 60 mm -- comfortably above the
~30 mm by which the rebuilt panel legitimately differs from the melt it
replaces, and far below the several hundred mm a real hole exposes.

Run: python3 verify_holes.py <before.glb> <after.glb> <out.json> [--selftest]
"""
import json, sys
import numpy as np, trimesh

BEF, AFT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SELFTEST = "--selftest" in sys.argv


def scene_tris(path, punch=None):
    sc = trimesh.load(path, force="scene", process=False)
    T = []
    for n in sc.graph.nodes_geometry:
        M, gname = sc.graph[n]
        g = sc.geometry[gname]
        tri = trimesh.transform_points(g.vertices, M)[g.faces]
        if punch is not None and gname in punch[0]:
            c = tri.mean(1)
            keep = np.linalg.norm(c - np.array(punch[1]), axis=1) > punch[2]
            tri = tri[keep]
        T.append(tri)
    T = np.vstack(T)
    return trimesh.Trimesh(vertices=T.reshape(-1, 3),
                           faces=np.arange(len(T) * 3).reshape(-1, 3), process=False)


DIRS = [(az, el) for az in (0, -22, 22, -40, 40) for el in (0, -18, 18)]


TOL = 0.060


def hit_mask(mesh, n=44):
    ext = mesh.bounds
    ctr = ext.mean(0)
    ys = np.linspace(0.16, 1.36, n)
    zs = np.linspace(-0.86, 0.80, n)
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    masks = {}
    for az, el in DIRS:
        a, e = np.radians(az), np.radians(el)
        d = np.array([-np.cos(e) * np.cos(a), -np.sin(e), -np.cos(e) * np.sin(a)])
        # rays aimed at the rear zone, launched from well outside it
        tgt = np.stack([np.full(Y.size, 2.05), Y.ravel(), Z.ravel()], 1)
        o = tgt - 3.0 * d
        loc, ir, _ = mesh.ray.intersects_location(o, np.tile(d, (len(o), 1)),
                                                  multiple_hits=False)
        depth = np.full(len(o), np.inf)
        if len(ir):
            dd = np.linalg.norm(loc - o[ir], axis=1)
            np.minimum.at(depth, ir, dd)
        masks[f"az{az:+d}_el{el:+d}"] = depth.reshape(n, n)
    return masks


mb = scene_tris(BEF)
# THE CONTROL MUST PUNCH BOTH SKINS. First attempt punched only "Hatch" and the
# probe correctly reported nothing: the tailgate is a closed pressing, so a hole
# in the outer skin exposes its OWN inner skin 14 mm behind -- a 14 mm recession,
# far under the 60 mm tolerance. That is not a failure of the probe, it is the
# panel being a real pressing rather than a sheet. A through-hole has to remove
# both skins, and then the next surface is the cabin, hundreds of mm away.
ma = scene_tris(AFT, punch=({"Hatch", "Hatch_Inner"}, (2.02, 0.72, 0.05), 0.09)
                if SELFTEST else None)
MB_, MA_ = hit_mask(mb), hit_mask(ma)
rep = {"selftest": SELFTEST, "directions": len(DIRS), "per_direction": {}}
tot_lost = tot_before = 0
for k in MB_:
    b, a = MB_[k], MA_[k]
    hb = np.isfinite(b)
    gone = hb & ~np.isfinite(a)
    receded = hb & np.isfinite(a) & ((a - b) > TOL)
    lost = int((gone | receded).sum())
    rep["per_direction"][k] = {"hit_before": int(hb.sum()),
                               "hit_after": int(np.isfinite(a).sum()),
                               "gone": int(gone.sum()), "receded": int(receded.sum()),
                               "lost": lost,
                               "max_recession_mm": (round(float(np.nanmax(
                                   np.where(hb & np.isfinite(a), a - b, np.nan)) * 1000), 1)
                                   if (hb & np.isfinite(a)).any() else None)}
    tot_lost += lost; tot_before += int(hb.sum())
seam = {k: int(v["receded"]) for k, v in rep["per_direction"].items()}
rep["total_gone"] = int(sum(v["gone"] for v in rep["per_direction"].values()))
rep["total_receded"] = int(sum(v["receded"] for v in rep["per_direction"].values()))
rep["total_rays_hit_before"] = tot_before
rep["total_rays_lost"] = tot_lost
rep["pct_lost"] = round(100.0 * tot_lost / max(tot_before, 1), 4)
json.dump(rep, open(OUT, "w"), indent=1)
print(json.dumps({k: rep[k] for k in ("selftest", "total_rays_hit_before", "total_gone",
                                      "total_receded", "total_rays_lost", "pct_lost")}, indent=1))
worst = sorted(rep["per_direction"].items(), key=lambda kv: -kv[1]["lost"])[:4]
for k, v in worst: print(" ", k, v)
