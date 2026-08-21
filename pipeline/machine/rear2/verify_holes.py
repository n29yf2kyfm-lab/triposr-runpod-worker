#!/usr/bin/env python3
"""verify_holes.py — did the cut open a hole? 15 directions, before vs after.

A ray that HIT the car before the cut and MISSES it afterwards is a hole, by
definition. Nothing else in this test is interpretation.

Directions: az 0 / +-22 / +-40 x el 0 / +-18, all relative to the rear axis
(+X on this file, established by render).

NEGATIVE CONTROL is mandatory here -- CLAUDE.md records two checks on this
programme that were EMPTY BY CONSTRUCTION and reported PASS forever. Run with
--selftest to delete a disc of faces from the rebuilt tailgate and confirm the
probe reports the hole. A test that has never fired is not a test.

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
        if punch is not None and gname == punch[0]:
            c = tri.mean(1)
            keep = np.linalg.norm(c - np.array(punch[1]), axis=1) > punch[2]
            tri = tri[keep]
        T.append(tri)
    T = np.vstack(T)
    return trimesh.Trimesh(vertices=T.reshape(-1, 3),
                           faces=np.arange(len(T) * 3).reshape(-1, 3), process=False)


DIRS = [(az, el) for az in (0, -22, 22, -40, 40) for el in (0, -18, 18)]


def hit_mask(mesh, n=70):
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
        hits = mesh.ray.intersects_any(o, np.tile(d, (len(o), 1)))
        masks[f"az{az:+d}_el{el:+d}"] = hits.reshape(n, n)
    return masks


mb = scene_tris(BEF)
ma = scene_tris(AFT, punch=("Hatch", (2.00, 0.72, 0.05), 0.09) if SELFTEST else None)
MB_, MA_ = hit_mask(mb), hit_mask(ma)
rep = {"selftest": SELFTEST, "directions": len(DIRS), "per_direction": {}}
tot_lost = tot_before = 0
for k in MB_:
    b, a = MB_[k], MA_[k]
    lost = int((b & ~a).sum()); gained = int((~b & a).sum())
    rep["per_direction"][k] = {"hit_before": int(b.sum()), "hit_after": int(a.sum()),
                               "lost": lost, "gained": gained}
    tot_lost += lost; tot_before += int(b.sum())
rep["total_rays_hit_before"] = tot_before
rep["total_rays_lost"] = tot_lost
rep["pct_lost"] = round(100.0 * tot_lost / max(tot_before, 1), 4)
json.dump(rep, open(OUT, "w"), indent=1)
print(json.dumps({k: rep[k] for k in ("selftest", "total_rays_hit_before",
                                      "total_rays_lost", "pct_lost")}, indent=1))
worst = sorted(rep["per_direction"].items(), key=lambda kv: -kv[1]["lost"])[:4]
for k, v in worst: print(" ", k, v)
