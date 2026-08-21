#!/usr/bin/env python3
"""wins.py — measure EACH GATE'S OWN WIN on the merged car.

The merge brief fixes six numbers, one per gate, and requires each to be
measured on the merged output rather than quoted from the gate that produced it.
Quoting is what the brief forbids and what CLAUDE.md's Gate 3 v6 entry is about:
a verifier certifying a sha proves nothing once the file behind it is gone.

Each measurement here re-derives the gate's own quantity with the gate's own
definition where the tool exists, and with an explicitly stated estimator where
it does not.  Where the merged car cannot carry a gate's win, that is SAID.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glbmeas                                                   # noqa: E402
import collide                                                   # noqa: E402


def merge_win(path):
    """all four tyre bottoms at 0.000 mm, measured from TRANSFORMED vertices."""
    m = glbmeas.measure(path)
    t = {k: round(v * 1000, 4) for k, v in m["tyre_node_min_y"].items()}
    return {"tyre_bottom_mm": t,
            "max_abs_mm": round(max(abs(v) for v in t.values()), 4),
            "note": "world-space minima of the TYRE nodes, not the whole-model "
                    "bbox -- viewer_check's on_ground reads the latter and passes "
                    "a car with its front tyres 183 mm in the air"}


def glass_win(path):
    m = glbmeas.measure(path)
    return {"Glass_Windscreen_m2": round(m["glass_area_by_node"]
                                         .get("Glass_Windscreen", 0.0), 6),
            "glazing_by_node": {k: round(v, 6)
                                for k, v in m["glass_area_by_node"].items()},
            "projected_opening_m2": m["glass_projected_m2"]["max"],
            "crumple_ratio": m["glass_crumple_ratio"]}


def provenance(merged, base, nodes):
    """Gate 3 v6's test: what share of a node's face CENTROIDS coincides with a
    source centroid.  A rebuilt part scores 0.00%; inherited geometry scores
    100% at 0 mm.  An INHERITED control is always included so a row of zeros
    cannot be read as a passing result when the test is simply broken.

    MEASURE THIS PRE-POSE.  Run against the FINAL car it returns 0.0% for
    `Body_Shell` too -- which is not evidence that the shell was rebuilt, it is
    the pose stage having moved every vertex by a rigid 4.7301 deg rotation and
    a 101.6 mm drop.  Provenance is invariant under that transform, so the
    honest place to measure it is the last pre-pose car, in the frame the gates
    themselves worked in.  I ran it on the posed file first and got exactly that
    row of zeros; it is recorded here so the next reader does not repeat it.
    """
    from scipy.spatial import cKDTree
    A = collide.node_geom(merged)
    B = collide.node_geom(base)
    allb = np.vstack([v[2] for v in B.values()])
    tree = cKDTree(allb)
    out = {}
    for n in nodes:
        if n not in A:
            out[n] = "absent"
            continue
        d, _ = tree.query(A[n][2], k=1, workers=2)
        out[n] = {"faces": int(len(d)),
                  "pct_coincident_at_1um": round(float(100 * (d < 1e-6).mean()), 4),
                  "median_nearest_mm": round(float(np.median(d) * 1000), 3)}
    return out


def rear_hidden_melt(merged, work):
    """Rays through the rebuilt panels: is a NON-REBUILT surface still within
    100 mm behind the new skin?  rear v2 measured hatch 1.92% / bumper 3.61%
    after its rebuild, against 97.52% / 100.0% before.
    """
    import trimesh
    sc = trimesh.load(merged, force="scene", process=False)
    G = {}
    for n in sc.graph.nodes_geometry:
        T, g = sc.graph[n]
        gg = sc.geometry[g].copy()
        gg.apply_transform(T)
        G[n] = gg
    REB = ("Hatch", "Hatch_Inner", "Bumper_Rear", "Bumper_Rear_Inner",
           "Plate_Rear", "Glass_Backlight")
    out = {}
    for panel, others in (("Hatch", REB), ("Bumper_Rear", REB)):
        if panel not in G:
            out[panel] = "absent"
            continue
        P = G[panel]
        # sample the panel, step 5 mm outward, shoot INWARD (-x is forward)
        idx = np.random.default_rng(0).choice(len(P.faces),
                                              size=min(1500, len(P.faces)),
                                              replace=False)
        org = P.triangles_center[idx] + np.array([0.005, 0, 0])
        dirs = np.tile(np.array([-1.0, 0, 0]), (len(org), 1))
        hit_reb, hit_other = 0, 0
        for name, g in G.items():
            if name in ("Interior",):
                continue
            try:
                loc, ray, _ = g.ray.intersects_location(org, dirs, multiple_hits=False)
            except Exception:
                continue
            if len(ray) == 0:
                continue
            dist = np.abs(loc[:, 0] - org[ray][:, 0])
            near = ray[dist < 0.100]
            if name in others:
                hit_reb += len(np.unique(near))
            else:
                hit_other += len(np.unique(near))
        out[panel] = {"rays": int(len(org)),
                      "rays_with_a_NON_rebuilt_surface_within_100mm":
                          int(hit_other),
                      "pct": round(100 * hit_other / max(len(org), 1), 3)}
    json.dump(out, open(os.path.join(work, "rear_hidden_melt.json"), "w"), indent=1)
    return out


def cabin_through_glass(merged, work):
    """What does the glazing SHOW?  The cabin gate's question, re-measured.

    Its own instrument rasterises 8 frozen cameras and attributes every
    through-glass pixel to the node behind it.  Reproduced here on the merged
    car with the same rasteriser, so the number is comparable to its 69.9% ->
    8.0%.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "cabin"))
    import raster                                                # noqa: E402
    import trimesh
    import cabin_rigcfg
    cfg_p = os.path.join(work, "rig_cfg_win.json")
    cabin_rigcfg.write(merged, cfg_p)
    cams, cfg = raster.cams_from_cfg(cfg_p)
    sc = trimesh.load(merged, force="scene", process=False)
    V, F, own, names = [], [], [], []
    off = 0
    for n in sc.graph.nodes_geometry:
        T, g = sc.graph[n]
        v = trimesh.transform_points(np.asarray(sc.geometry[g].vertices, float), T)
        f = np.asarray(sc.geometry[g].faces, np.int64) + off
        V.append(v)
        F.append(f)
        own.append(np.full(len(f), len(names)))
        names.append(n)
        off += len(v)
    V = raster.gltf_to_blender(np.vstack(V))
    F = np.vstack(F)
    own = np.concatenate(own)
    GL = [i for i, n in enumerate(names) if n.startswith("Glass_")]
    glass_f = np.isin(own, GL)
    tally = {}
    tot = 0
    for cname, cam in cams.items():
        idg, zg = raster.rasterise(cam, V, F[glass_f], keep="near")
        idn, zn = raster.rasterise(cam, V, F[~glass_f], keep="near")
        on = (idg > 0)
        behind = on & (idn > 0) & (zn > zg)
        tot += int(behind.sum())
        o = own[~glass_f][idn[behind] - 1]
        for k in np.unique(o):
            tally[names[k]] = tally.get(names[k], 0) + int((o == k).sum())
    res = {"through_glass_px": tot,
           "share_by_node_pct": {k: round(100 * v / max(tot, 1), 2)
                                 for k, v in sorted(tally.items(),
                                                    key=lambda x: -x[1])[:14]}}
    res["Interior_share_pct"] = res["share_by_node_pct"].get("Interior", 0.0)
    res["Cabin_share_pct"] = round(sum(v for k, v in res["share_by_node_pct"].items()
                                       if k.startswith("Cabin_")), 2)
    json.dump(res, open(os.path.join(work, "through_glass.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    merged, base, work = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(work, exist_ok=True)
    out = {"merged": os.path.basename(merged),
           "merged_sha256": glbmeas.sha256(merged)}
    which = sys.argv[4] if len(sys.argv) > 4 else "all"
    if which in ("all", "merge"):
        out["merge_gate"] = merge_win(merged)
    if which in ("all", "glass"):
        out["glass_gate"] = glass_win(merged)
    if which in ("all", "front"):
        out["front_v7_provenance"] = provenance(
            merged, base,
            ["Grille_Upper", "Grille_Lower", "Headlamp_L_Lens", "Headlamp_R_Lens",
             "Badge", "Plate", "Valance_Front", "Intake_L", "Bumper_Front",
             "Body_Shell"])
    if which in ("all", "rearprov"):
        out["rear_v2_provenance"] = provenance(
            merged, base,
            ["Hatch", "Hatch_Inner", "Bumper_Rear", "Bumper_Rear_Inner",
             "Plate_Rear", "Glass_Backlight", "TailLamp_L"])
    if which in ("all", "cabinprov"):
        out["cabin_provenance"] = provenance(
            merged, base,
            ["Cabin_Dash", "Cabin_SeatFD_Cush", "Cabin_Headliner", "Cabin_Wheel"])
    if which in ("all", "rear"):
        out["rear_v2_hidden_melt"] = rear_hidden_melt(merged, work)
    if which in ("all", "cabin"):
        out["cabin_through_glass"] = cabin_through_glass(merged, work)
    p = os.path.join(work, f"WINS_{which}.json")
    json.dump(out, open(p, "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))
