#!/usr/bin/env python3
"""collide.py — the cross-gate collision scan, run on the MERGED car.

Six gates each built against `car_rebound` alone, so no gate's own report can
say whether its component lands on top of another gate's, or on top of the base
part it is supposed to supersede.  The independent verifier found both classes
and fixed them as acceptance items A21/A22.

Two questions, and they are different:

  A21  ARE TWO GLAZING NODES STACKED?  Two transmissive sheets in the same place
       is the recorded WHITE-DOT DEFECT — overlapping quadric sheets bloom white
       under grazing transmission, and it survived six wrong theories the last
       time.  Threshold: no more than 5% of EITHER node within 25 mm of the
       other.

  A22  IS EVERY SUPERSEDED BASE PART ACTUALLY GONE?  A constructed component
       laid over surviving melt is the parts-over-melt failure that killed
       Gate 3 v5 and v6, re-entering through the merge rather than through a
       single gate.

The measure is SYMMETRIC and reported both ways.  `share_within(A, B)` is the
fraction of A's face centroids within `tol` of any B vertex — it is NOT
symmetric, and reporting one direction only is how "96% overlapped" and "27%
overlapped" can describe the same pair.  A large panel that SURROUNDS a small
one scores low one way and high the other; a genuine stack scores high both.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glbmeas                                                   # noqa: E402

TOL = 0.025
MEDIAN_STACK_MM = 50.0        # see the stacked/adjacent note in scan()

# A21: every glazing node must be disjoint from every other glazing node.
# A22: (constructed component, the base part it supersedes).
SUPERSEDES = [
    ("Valance_Front", "Bumper_Front_Paint"),
    ("Intake_L", "Bumper_Front_Paint"),
    ("Intake_R", "Bumper_Front_Paint"),
    ("Intake_L", "Headlamp_L"),
    ("Intake_R", "Headlamp_R"),
    ("Grille_Lower", "Bumper_Front_Paint"),
    ("Grille_Upper", "Bumper_Front_Paint"),
    ("Bumper_Rear_Inner", "Bumper_Rear_Paint"),
    ("Bumper_Rear", "Bumper_Rear_Paint"),
    ("Plate_Rear", "Bumper_Rear_Paint"),
    ("Hatch_Inner", "Bumper_Rear_Paint"),
    ("Hatch", "Body_Shell"),
    ("Cabin_Floor", "Body_Shell"),
    ("Cabin_Headliner", "Interior"),
]


def node_geom(path):
    g = glbmeas.GLB(path)
    out = {}
    for ni, name, W, mi in g.graph():
        V, F = [], []
        off = 0
        for p in g.g["meshes"][mi].get("primitives", []):
            v = g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
            v = v @ W[:3, :3].T + W[:3, 3]
            f = g.accessor(p["indices"]).astype(np.int64).reshape(-1, 3) + off
            V.append(v)
            F.append(f)
            off += len(v)
        if not V:
            continue
        V = np.vstack(V)
        F = np.vstack(F)
        out[name] = (V, F, V[F].mean(1))
    return out


def share_within(A, B, tol=TOL):
    """fraction of A's face CENTROIDS within tol of any B VERTEX."""
    if A is None or B is None:
        return None, None
    tree = cKDTree(B[0])
    d, _ = tree.query(A[2], k=1, workers=2)
    return float(100 * (d < tol).mean()), float(np.median(d) * 1000)


def scan(path, out_json=None):
    G = node_geom(path)
    m = glbmeas.measure(path)
    glass_nodes = sorted(m["glass_area_by_node"])
    rep = {"file": os.path.basename(path), "tol_mm": TOL * 1000,
           "glass_nodes": glass_nodes, "A21": [], "A22": [], "nodes": sorted(G)}

    for i, a in enumerate(glass_nodes):
        for b in glass_nodes[i + 1:]:
            sa, ma = share_within(G.get(a), G.get(b))
            sb, mb = share_within(G.get(b), G.get(a))
            if sa is None or sb is None:
                continue
            rep["A21"].append({
                "a": a, "b": b,
                "share_a_in_b_pct": round(sa, 2), "share_b_in_a_pct": round(sb, 2),
                "median_a_to_b_mm": round(ma, 1), "median_b_to_a_mm": round(mb, 1),
                # A STACK AND AN ADJACENCY ARE NOT THE SAME THING, and a share
                # threshold alone cannot tell them apart.  Two panes that MEET
                # at the A-pillar put ~7% of each other's faces within 25 mm of
                # the seam while their medians sit 468 and 487 mm apart; a
                # genuine stack scores 96.8% at a median of 6.0 mm.  So a stack
                # requires a high share AND a small median separation.
                "stacked": bool(max(sa, sb) > 5.0 and min(ma, mb) < MEDIAN_STACK_MM)})
    rep["A21_pass"] = not any(r["stacked"] for r in rep["A21"])

    for comp, base in SUPERSEDES:
        if comp not in G:
            rep["A22"].append({"component": comp, "supersedes": base,
                               "status": "component absent"})
            continue
        if base not in G:
            rep["A22"].append({"component": comp, "supersedes": base,
                               "status": "base part fully removed", "share_pct": 0.0})
            continue
        s, md = share_within(G[comp], G[base])
        rep["A22"].append({"component": comp, "supersedes": base,
                           "status": "base part still present",
                           "share_pct": round(s, 2), "median_mm": round(md, 1),
                           "stacked": bool(s > 5.0)})
    rep["A22_pass"] = not any(r.get("stacked") for r in rep["A22"])
    rep["pass"] = bool(rep["A21_pass"] and rep["A22_pass"])
    if out_json:
        json.dump(rep, open(out_json, "w"), indent=1)
    return rep


if __name__ == "__main__":
    r = scan(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"A21 glazing-stack  {'PASS' if r['A21_pass'] else 'FAIL'}")
    for x in r["A21"]:
        if x["stacked"] or max(x["share_a_in_b_pct"], x["share_b_in_a_pct"]) > 1:
            print(f"   {x['a']:22s} vs {x['b']:22s} "
                  f"a_in_b {x['share_a_in_b_pct']:6.2f}%  b_in_a {x['share_b_in_a_pct']:6.2f}%"
                  f"  med {x['median_a_to_b_mm']:7.1f}/{x['median_b_to_a_mm']:7.1f} mm"
                  f"  {'STACKED' if x['stacked'] else ''}")
    print(f"A22 superseded-base {'PASS' if r['A22_pass'] else 'FAIL'}")
    for x in r["A22"]:
        print(f"   {x['component']:20s} -> {x['supersedes']:20s} {x['status']:26s}"
              + (f" share {x['share_pct']:6.2f}%"
                 + (f" med {x['median_mm']:7.1f} mm" if "median_mm" in x else "")
                 + f" {'STACKED' if x.get('stacked') else ''}" if "share_pct" in x else ""))
