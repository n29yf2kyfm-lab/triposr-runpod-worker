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

    # A22, MEASURED THE WAY THE QUESTION IS ASKED.
    #
    # "share of the COMPONENT within 25 mm of the base part" is the wrong
    # direction and it convicts a correct build: Gate 3 v7 DELIBERATELY leaves a
    # 12 mm flange of original bodywork at every cut edge and ramps each new
    # panel 10 mm rearward over its last 16 mm so it passes BEHIND that flange.
    # A small new part adjacent to a large surviving surface therefore scores
    # 90%+ by construction, and did (Valance_Front 97.66%).
    #
    # The defect this item exists to catch is PARTS OVER MELT -- base geometry
    # standing OUTSIDE the component that replaces it.  So the verdict is taken
    # on `base_proud_share`: among base faces near the component, the share that
    # sit RADIALLY FURTHER FROM THE CAR'S CENTRE than the component does, by
    # more than 2 mm.  Radial is used rather than a per-part normal because it
    # needs no assumption about which way each panel faces, and the fascia, the
    # tail and the flanks are all convex outward on this body.
    #
    # INTERIOR components are exempt from the proud rule and marked so: a cabin
    # floor is SUPPOSED to sit inside the floorpan, and "the body is further from
    # the centre than the carpet" is not a defect.
    ctr = np.mean([v[0].mean(0) for v in G.values()], axis=0)
    for comp, base in SUPERSEDES:
        row = {"component": comp, "supersedes": base}
        if comp not in G:
            row["status"] = "component absent"
            rep["A22"].append(row); continue
        if base not in G:
            row.update(status="base part fully removed", share_pct=0.0,
                       base_proud_share_pct=0.0, stacked=False)
            rep["A22"].append(row); continue
        s_cb, md_cb = share_within(G[comp], G[base])
        s_bc, md_bc = share_within(G[base], G[comp])
        tree = cKDTree(G[comp][0])
        Cb = G[base][2]
        d, i = tree.query(Cb, k=1, workers=2)
        near = d < TOL
        interior = comp.startswith("Cabin_")
        if near.sum() >= 20:
            r_base = np.linalg.norm(Cb[near] - ctr, axis=1)
            r_comp = np.linalg.norm(G[comp][0][i][near] - ctr, axis=1)
            proud = float(100 * ((r_base - r_comp) > 0.002).mean())
            med_off = float(np.median(r_base - r_comp) * 1000)
        else:
            proud, med_off = 0.0, 0.0
        row.update(status="base part still present",
                   share_comp_in_base_pct=round(s_cb, 2),
                   share_base_in_comp_pct=round(s_bc, 2),
                   median_comp_to_base_mm=round(md_cb, 1),
                   median_base_to_comp_mm=round(md_bc, 1),
                   base_faces_near=int(near.sum()),
                   base_proud_share_pct=round(proud, 2),
                   median_radial_offset_mm=round(med_off, 2),
                   interior_exempt=interior,
                   stacked=bool((not interior) and proud > 20.0 and s_bc > 20.0))
        rep["A22"].append(row)
    rep["A22_pass"] = not any(r.get("stacked") for r in rep["A22"])
    rep["pass"] = bool(rep["A21_pass"] and rep["A22_pass"])
    if out_json:
        json.dump(rep, open(out_json, "w"), indent=1)
    return rep


def selftest(path, workdir):
    """Prove A21 and A22 can FAIL.  A gate nobody has seen fire does not exist.

    NC-A21: duplicate a glazing node in place -> two transmissive sheets at 0 mm.
    NC-A22: shove the whole v7 front kit 40 mm REARWARD, so the surviving base
            flange stands proud of it.  That is exactly the parts-over-melt
            geometry, injected.
    NC-A22b: shove it 40 mm FORWARD instead.  The rule is directional and this
            one must still PASS -- a control that fires on everything is no
            better than one that fires on nothing.
    """
    import struct
    os.makedirs(workdir, exist_ok=True)
    KIT = ("Valance_Front", "Intake_L", "Intake_R", "Intake_L_Blades",
           "Intake_R_Blades", "Grille_Lower", "Grille_Upper", "Badge",
           "Badge_Mount", "Plate", "Plate_Carrier", "DRL_Blade", "TowEye_Cover",
           "Bumper_Front", "Headlamp_L_Lens", "Headlamp_R_Lens",
           "Headlamp_L_Housing", "Headlamp_R_Housing",
           "Headlamp_L_Internal", "Headlamp_R_Internal")

    def shift(src, dst, dx):
        g = glbmeas.GLB(src)
        for nd in g.g["nodes"]:
            if nd.get("name") in KIT:
                t = list(nd.get("translation", [0.0, 0.0, 0.0]))
                t[0] += dx
                nd["translation"] = t
        j = json.dumps(g.g, separators=(",", ":")).encode()
        j += b" " * ((4 - len(j) % 4) % 4)
        b = bytes(g.bin)
        b += b"\0" * ((4 - len(b) % 4) % 4)
        with open(dst, "wb") as f:
            f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(j) + 8 + len(b)))
            f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
            f.write(struct.pack("<II", len(b), 0x004E4942) + b)

    def dupe_glass(src, dst):
        g = glbmeas.GLB(src)
        tgt = [n for n in g.g["nodes"] if n.get("name") == "Glass_Rear"]
        if not tgt:
            tgt = [n for n in g.g["nodes"] if n.get("name") == "Glass_Backlight"]
        nd = dict(tgt[0])
        nd["name"] = nd["name"] + "_DUPE"
        g.g["nodes"].append(nd)
        g.g["scenes"][g.g.get("scene", 0)]["nodes"].append(len(g.g["nodes"]) - 1)
        j = json.dumps(g.g, separators=(",", ":")).encode()
        j += b" " * ((4 - len(j) % 4) % 4)
        b = bytes(g.bin)
        b += b"\0" * ((4 - len(b) % 4) % 4)
        with open(dst, "wb") as f:
            f.write(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(j) + 8 + len(b)))
            f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
            f.write(struct.pack("<II", len(b), 0x004E4942) + b)

    out = {"base": scan(path)}
    out["base"] = {"A21_pass": out["base"]["A21_pass"],
                   "A22_pass": out["base"]["A22_pass"]}
    c1 = os.path.join(workdir, "NC_glass_dupe.glb")
    dupe_glass(path, c1)
    r1 = scan(c1)
    out["NC_A21_duplicate_glazing_node"] = {
        "A21_pass": r1["A21_pass"], "fired": not r1["A21_pass"],
        "worst": max((x for x in r1["A21"]), key=lambda x: max(
            x["share_a_in_b_pct"], x["share_b_in_a_pct"]))}
    c2 = os.path.join(workdir, "NC_kit_rearward.glb")
    shift(path, c2, +0.040)
    r2 = scan(c2)
    out["NC_A22_kit_40mm_rearward"] = {
        "A22_pass": r2["A22_pass"], "fired": not r2["A22_pass"],
        "rows": [x for x in r2["A22"] if x.get("stacked")]}
    c3 = os.path.join(workdir, "NC_kit_forward.glb")
    shift(path, c3, -0.040)
    r3 = scan(c3)
    out["NC_A22b_kit_40mm_forward_must_still_pass"] = {
        "A22_pass": r3["A22_pass"], "correctly_passes": r3["A22_pass"]}
    for c in (c1, c2, c3):
        os.remove(c)
    out["all_fired"] = bool(out["NC_A21_duplicate_glazing_node"]["fired"]
                            and out["NC_A22_kit_40mm_rearward"]["fired"]
                            and out["NC_A22b_kit_40mm_forward_must_still_pass"]
                            ["correctly_passes"])
    return out


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest(sys.argv[1], sys.argv[3] if len(sys.argv) > 3 else "nc_collide")
        print(json.dumps(r, indent=1, default=str))
        sys.exit(0 if r["all_fired"] else 1)
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
        if "base_proud_share_pct" not in x:
            print(f"   {x['component']:20s} -> {x['supersedes']:20s} {x['status']}")
            continue
        print(f"   {x['component']:20s} -> {x['supersedes']:20s} "
              f"comp_in_base {x.get('share_comp_in_base_pct', 0):6.2f}%  "
              f"base_in_comp {x.get('share_base_in_comp_pct', 0):6.2f}%  "
              f"BASE PROUD {x['base_proud_share_pct']:6.2f}% "
              f"(median radial {x.get('median_radial_offset_mm', 0):+7.2f} mm)"
              + ("  [interior, exempt]" if x.get("interior_exempt") else "")
              + ("  PARTS-OVER-MELT" if x.get("stacked") else ""))
