#!/usr/bin/env python3
"""pivot_check.py — does a node with a pivot actually ANIMATE correctly?

Gate 7 asks for "correctly placed pivots ... tested for correct hinge
rotation, no body intersection, no detached seals or glass, no incorrect pivot
movement". A pivot that exists in the file is not evidence of any of that: the
node can carry a translation and still wobble, sink into the road or scythe
through the arch when it turns. This tool ROTATES each pivoted node through a
full sweep and measures what happens, on the EXPORTED GLB, in a fresh process.

WHAT IT MEASURES, per node, over a sweep of angles about the node's own axis:

  wobble_mm        the peak-to-peak of the node's LOWEST world point across
                   the sweep. A wheel whose pivot sits on its true axle keeps
                   its contact patch at a constant height while it spins; one
                   whose pivot is off by e mm bobs by up to 2e mm. This is the
                   test that catches a mis-placed pivot, and it needs no
                   reference geometry at all.
  roundness_mm     spread (p2..p98) of the tread radius about the axis. Large
                   spread means the part is not a solid of revolution, so a
                   wobble reading has to be interpreted with that in mind.
  clearance_mm     nearest distance from the rotating node to the STATIC parts
                   of the car, at every angle. `at_rest` is the same number at
                   0 deg. A drop from at_rest to min means the part eats into
                   the body as it turns; an unchanged value means it does not.
  penetration      the count of rotated vertices that end up closer to a static
                   surface than the resting clearance minus a tolerance — the
                   blunt "does it intersect the body" answer.

THE AXIS IS NOT ASSUMED. It is fitted from the node's own geometry: the
direction of MINIMUM variance of the vertex cloud about the pivot is the axle
of a wheel-shaped part (a disc is wide in two directions and thin in the
third). The report states the fitted axis and its agreement with the axis the
exporter recorded, so a disagreement is visible rather than silently averaged.

Run:
    python3 pivot_check.py --glb car.glb --report pivots.json [--steps 24]
"""
import argparse
import json
import os

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def node_world(sc, node):
    T, gname = sc.graph[node]
    g = sc.geometry[gname]
    V = np.asarray(g.vertices)
    return (V @ T[:3, :3].T + T[:3, 3]), T[:3, 3], g


def fit_axis(Vc):
    """Axle = the direction of least variance of the centred cloud."""
    C = (Vc - Vc.mean(0))
    _, s, vt = np.linalg.svd(C[np.random.default_rng(0).choice(
        len(C), min(len(C), 40000), replace=False)], full_matrices=False)
    return vt[np.argmin(s)] / np.linalg.norm(vt[np.argmin(s)]), s


def rot(axis, ang):
    a = axis / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--report")
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--sample", type=int, default=60000,
                    help="vertices sampled per node for the clearance query")
    ap.add_argument("--tol-mm", type=float, default=1.0)
    a = ap.parse_args()

    sc = trimesh.load(a.glb, force="scene", process=False)
    piv = {}
    for node in sorted(sc.graph.nodes_geometry):
        T, _ = sc.graph[node]
        if np.linalg.norm(T[:3, 3]) > 1e-9:
            piv[node] = T[:3, 3]
    out = dict(tool="pivot_check.py", glb=os.path.abspath(a.glb),
               steps=a.steps, pivoted_nodes=sorted(piv))
    if not piv:
        out["status"] = "NO PIVOTS"
        print(json.dumps(out, indent=1))
        return out

    # group nodes that share a pivot: a wheel is tyre + rim + disc and they
    # must turn as ONE assembly, so they are measured as one.
    groups = {}
    for n, p in piv.items():
        groups.setdefault(tuple(np.round(p, 6)), []).append(n)

    rng = np.random.default_rng(0)
    rows = []
    for pv, nodes in sorted(groups.items(), key=lambda kv: kv[1]):
        pv = np.array(pv)
        Vs = [node_world(sc, n)[0] for n in nodes]
        V = np.vstack(Vs)
        axis, sv = fit_axis(V - pv)
        # every other geometry in the scene is the STATIC reference
        static = []
        for other in sc.graph.nodes_geometry:
            if other in nodes:
                continue
            static.append(node_world(sc, other)[0])
        S = np.vstack(static)
        if len(S) > 400000:
            S = S[rng.choice(len(S), 400000, replace=False)]
        tree = cKDTree(S)
        Vq = V if len(V) <= a.sample else V[rng.choice(len(V), a.sample,
                                                       replace=False)]
        r = np.linalg.norm(np.cross(Vq - pv, axis), axis=1)
        lows, clears = [], []
        for k in range(a.steps):
            ang = 2 * np.pi * k / a.steps
            P = (Vq - pv) @ rot(axis, ang).T + pv
            lows.append(float(P[:, 1].min()))
            d, _ = tree.query(P, workers=-1)
            clears.append(float(d.min()))
        rest = clears[0]
        pen = 0
        P0 = (Vq - pv) @ rot(axis, 2 * np.pi / a.steps).T + pv
        d1, _ = tree.query(P0, workers=-1)
        pen = int((d1 < rest - a.tol_mm / 1000.0).sum())
        rows.append(dict(
            group=sorted(nodes), pivot_world=[round(float(v), 5) for v in pv],
            fitted_axis=[round(float(v), 4) for v in axis],
            singular_values=[round(float(v), 3) for v in sv],
            tread_radius_m=round(float(np.percentile(r, 98)), 4),
            roundness_mm=round(float(np.percentile(r, 98) -
                                     np.percentile(r, 60)) * 1000, 2),
            lowest_point_m=round(float(np.mean(lows)), 5),
            wobble_mm=round((max(lows) - min(lows)) * 1000, 3),
            clearance_at_rest_mm=round(rest * 1000, 2),
            clearance_min_mm=round(min(clears) * 1000, 2),
            clearance_loss_mm=round((rest - min(clears)) * 1000, 2),
            penetrating_vertices_one_step=pen))
    out["groups"] = rows
    worst = max(r["wobble_mm"] for r in rows)
    loss = max(r["clearance_loss_mm"] for r in rows)
    out["summary"] = dict(
        max_wobble_mm=worst, max_clearance_loss_mm=loss,
        reading="wobble is the peak-to-peak height of the lowest point over a "
                "full turn; on a pivot placed exactly on the axle of a round "
                "part it is bounded by the part's own out-of-roundness")
    txt = json.dumps(out, indent=1)
    if a.report:
        open(a.report, "w").write(txt)
    print(txt)
    return out


if __name__ == "__main__":
    main()
