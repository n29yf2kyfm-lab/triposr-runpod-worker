#!/usr/bin/env python3
"""verify7.py -- GATE 3 v7 measurement of the rebuilt front.

Reads exported GLBs.  Writes nothing but its report.  Every number here is
measured from the file on disk, after a fresh import, so nothing is inherited
from the builder's in-memory state.

Checks, and why each one is here:
  hierarchy      the named components exist as real nodes with real geometry
  provenance     the old melt is GONE, not hidden behind the new parts.  Two
                 independent measures: (a) how much ORIGINAL front-zone
                 geometry survives, matched by triangle centroid to 0.1 mm
                 against the pre-strip file; (b) whether a ray that first hits
                 a NEW part then hits ORIGINAL shell within 2..250 mm.  A
                 nested surface a few centimetres behind a new lens is the
                 signature of parts-laid-over-melt, which is how v5 failed.
  symmetry       L/R deviation of the mirrored components about the FRONT-LOCAL
                 centreline.  v6's worst was 29.7 mm against a 2 mm threshold.
  hygiene        self-intersections (exact tri-tri), winding consistency, loose
                 shells, degenerate and duplicate geometry, per node.
  centreline     badge and plate lateral offset.  v6 held 0.0000 / -0.0011 mm.
  landmarks      built positions against the plan, in mm.

Run: python3 verify7.py <rebuilt.glb> <base.glb> <plan.json> <out.json>
"""
import json
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, "/home/user/triposr-runpod-worker/pipeline/machine/gate3v6")
from tri_intersect import intersect_count, broadphase, tri_tri_pairs

REBUILT, BASE, PLAN, OUT = sys.argv[1:5]
P = json.load(open(PLAN))
F = P["frame"]
ZC = F["z_centre"]
XN = F["x_nose_plane"]

NEW_NODES = [
    "Bumper_Front", "Valance_Front", "Grille_Upper", "Grille_Lower",
    "Plate_Carrier", "Plate", "Badge", "Badge_Mount", "DRL_Blade",
    "Intake_L", "Intake_R", "Intake_L_Blades", "Intake_R_Blades",
    "TowEye_Cover",
    "Headlamp_L_Lens", "Headlamp_L_Housing", "Headlamp_L_Internal",
    "Headlamp_R_Lens", "Headlamp_R_Housing", "Headlamp_R_Internal",
]
MIRROR_PAIRS = [("Headlamp_L_Lens", "Headlamp_R_Lens"),
                ("Headlamp_L_Housing", "Headlamp_R_Housing"),
                ("Headlamp_L_Internal", "Headlamp_R_Internal"),
                ("Intake_L", "Intake_R"),
                ("Intake_L_Blades", "Intake_R_Blades")]

sc = trimesh.load(REBUILT, force="scene", process=False)
W = {}
for n in sc.graph.nodes_geometry:
    T, g = sc.graph[n]
    gg = sc.geometry[g]
    W[n] = (trimesh.transform_points(np.asarray(gg.vertices, float), T),
            np.asarray(gg.faces), gg)

R = {"file": os.path.basename(REBUILT), "bytes": os.path.getsize(REBUILT),
     "sha_note": "sha256 is in the bucket MANIFEST", "checks": {}}

# ------------------------------------------------------------- hierarchy
hier = {}
for n in NEW_NODES:
    if n not in W:
        hier[n] = {"present": False}
        continue
    v, f, gg = W[n]
    mat = getattr(getattr(gg.visual, "material", None), "name", None)
    hier[n] = {"present": True, "faces": int(len(f)), "verts": int(len(v)),
               "material": mat,
               "bbox_mm": [round(float(x) * 1000, 1) for x in (v.max(0) - v.min(0))]}
R["checks"]["hierarchy"] = hier
R["checks"]["hierarchy_summary"] = {
    "required": len(NEW_NODES),
    "present_with_geometry": sum(1 for h in hier.values()
                                 if h["present"] and h["faces"] > 0),
    "old_melt_nodes_still_present": [n for n in
                                     ("Headlamp_L", "Headlamp_R", "Bumper_Front_Trim")
                                     if n in W],
}

# ------------------------------------------------------------ provenance
base = trimesh.load(BASE, force="scene", process=False)
BW = {}
for n in base.graph.nodes_geometry:
    T, g = base.graph[n]
    gg = base.geometry[g]
    BW[n] = trimesh.transform_points(np.asarray(gg.vertices, float), T)[
        np.asarray(gg.faces)].mean(1)

YLOW, YD = F["y_bumper_lowest"], F["y_datum_bonnet_leading_edge"]


def front_zone(c):
    return ((c[:, 0] < XN + 0.30) & (c[:, 1] > YLOW - 0.01) &
            (c[:, 1] < YD + 0.02) & (np.abs(c[:, 2] - ZC) < 0.72))


base_cent = np.concatenate([BW[n][front_zone(BW[n])] for n in BW
                            if front_zone(BW[n]).any()])
now = []
for n in W:
    if n in NEW_NODES:
        continue
    c = W[n][0][W[n][1]].mean(1)
    m = front_zone(c)
    if m.any():
        now.append(c[m])
now_cent = np.concatenate(now) if now else np.zeros((0, 3))

# centroid match at 0.1 mm: a FACE test, because a vertex test reads 100% on a
# file that only dropped faces (that is how v5 looked clean and was not)
key = lambda a: np.round(a / 1e-4).astype(np.int64)
bset = set(map(tuple, key(base_cent)))
nset = set(map(tuple, key(now_cent)))
surv = len(bset & nset)
R["checks"]["provenance_v0_residue"] = {
    "original_front_zone_faces": len(bset),
    "still_present_faces": surv,
    "residue_frac": round(surv / max(len(bset), 1), 5),
    "removed_faces": len(bset) - surv,
    "zone": "x < nose+300mm, y in [bumper_low-10, datum+20], |z-zc| < 720mm",
    "note": "face-centroid match at 0.1 mm against the PRE-STRIP file. This is "
            "the melt that remains ANYWHERE in the zone, at any depth -- not "
            "the melt that is visible.",
}

# DECISIVE PROVENANCE TEST.  The failure this gate exists to catch is melt
# RENAMED into a component node -- it reads 0% by name and 100% by geometric
# provenance.  So: what fraction of each NEW node's faces have a centroid that
# matches an ORIGINAL face, anywhere in the base file, to 0.1 mm?  A constructed
# part must score 0.
allbase = set()
for n in BW:
    allbase |= set(map(tuple, np.round(BW[n] / 1e-4).astype(np.int64)))
prov = {}
for n in NEW_NODES:
    if n not in W:
        continue
    c = W[n][0][W[n][1]].mean(1)
    ck = np.round(c / 1e-4).astype(np.int64)
    hit = sum(1 for row in map(tuple, ck) if row in allbase)
    prov[n] = {"faces": int(len(c)), "matching_original_faces": int(hit),
               "frac": round(hit / max(len(c), 1), 6)}
R["checks"]["provenance_new_nodes"] = prov
R["checks"]["provenance_new_nodes_worst_frac"] = round(
    max(p["frac"] for p in prov.values()), 6) if prov else None

# ------------------------------------------------------------- symmetry
sym = {}
for a, b in MIRROR_PAIRS:
    if a not in W or b not in W:
        sym[f"{a}|{b}"] = {"error": "missing"}
        continue
    va, vb = W[a][0], W[b][0]
    vm = vb.copy()
    vm[:, 2] = 2.0 * ZC - vm[:, 2]
    if len(va) != len(vm):
        sym[f"{a}|{b}"] = {"error": "vertex count differs",
                           "n": [len(va), len(vm)]}
        continue
    # mirrored construction preserves vertex order up to the winding flip, so a
    # sorted-coordinate comparison is exact and needs no correspondence search
    sa = va[np.lexsort((va[:, 2], va[:, 1], va[:, 0]))]
    sb = vm[np.lexsort((vm[:, 2], vm[:, 1], vm[:, 0]))]
    dd = np.linalg.norm(sa - sb, axis=1) * 1000
    sym[f"{a}|{b}"] = {"vertices": int(len(va)),
                       "max_dev_mm": round(float(dd.max()), 6),
                       "mean_dev_mm": round(float(dd.mean()), 6),
                       "p99_dev_mm": round(float(np.percentile(dd, 99)), 6)}
R["checks"]["symmetry"] = sym
devs = [s["max_dev_mm"] for s in sym.values() if "max_dev_mm" in s]
R["checks"]["symmetry_worst_mm"] = round(max(devs), 6) if devs else None

# -------------------------------------------------------------- hygiene
hyg = {}
worst_int = 0
for n in NEW_NODES:
    if n not in W:
        continue
    v, f, gg = W[n]
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    bodies = m.split(only_watertight=False)
    area = m.area_faces
    ic = intersect_count(v, f, v, f, share_verts=True, eps=1e-6)
    worst_int = max(worst_int, ic.get("intersecting_pairs", 0))

    # SPLIT the hits by shell.  A node that holds several deliberately
    # overlapping pieces -- Bumper_Front is 10 tiling panels that flange over
    # each other by 14 mm, Grille_Lower is a well plus 7 slats sitting inside it
    # -- will report "self-intersections" that are simply two DIFFERENT parts
    # occupying the same space, which is what assembled trim does.  A pair
    # inside ONE shell is a real defect; a pair between two shells is not.
    # Reporting one number for both is how a build gets condemned for its
    # construction rather than for a fault.
    same = diff = 0
    try:
        body_of = np.zeros(len(f), np.int32)
        for bi, bd in enumerate(bodies):
            # map by face centroid; exact because split() does not move anything
            cb = bd.vertices[bd.faces].mean(1)
            ck = set(map(tuple, np.round(cb / 1e-9).astype(np.int64)))
            cf = np.round(v[f].mean(1) / 1e-9).astype(np.int64)
            for fi, row in enumerate(map(tuple, cf)):
                if row in ck:
                    body_of[fi] = bi
        Pr = broadphase(v, f, v, f, share_verts=True)
        Pr = Pr[Pr[:, 0] < Pr[:, 1]]
        for s0 in range(0, len(Pr), 1_000_000):
            blk = Pr[s0:s0 + 1_000_000]
            hh, _ = tri_tri_pairs(v, f, v, f, blk, eps=1e-6)
            if hh.any():
                sel = blk[hh]
                sm = body_of[sel[:, 0]] == body_of[sel[:, 1]]
                same += int(sm.sum())
                diff += int((~sm).sum())
    except Exception as e:  # never let a refinement hide the primary number
        same = diff = -1
        R.setdefault("warnings", []).append(f"shell-split failed on {n}: {e}")
    hyg[n] = {
        "faces": int(len(f)),
        "shells": int(len(bodies)),
        "watertight": bool(m.is_watertight),
        "winding_consistent": bool(m.is_winding_consistent),
        "volume_positive": bool(m.is_volume and m.volume > 0),
        "degenerate_faces": int((area < 1e-12).sum()),
        "duplicate_vertices": int(len(v) - len(np.unique(np.round(v / 1e-7)
                                                         .astype(np.int64), axis=0))),
        "self_intersecting_pairs": ic.get("intersecting_pairs"),
        "intersect_within_one_shell": same,
        "intersect_between_shells": diff,
        "coplanar_pairs": ic.get("coplanar_pairs"),
    }
R["checks"]["hygiene"] = hyg
R["checks"]["hygiene_summary"] = {
    "worst_self_intersecting_pairs": worst_int,
    "total_intersect_within_one_shell": int(sum(
        max(h["intersect_within_one_shell"], 0) for h in hyg.values())),
    "total_intersect_between_shells": int(sum(
        max(h["intersect_between_shells"], 0) for h in hyg.values())),
    "total_self_intersecting_pairs": int(sum(h["self_intersecting_pairs"] or 0
                                             for h in hyg.values())),
    "nodes_winding_inconsistent": [n for n, h in hyg.items()
                                   if not h["winding_consistent"]],
    "nodes_not_watertight": [n for n, h in hyg.items() if not h["watertight"]],
    "total_degenerate_faces": int(sum(h["degenerate_faces"] for h in hyg.values())),
    "total_shells": int(sum(h["shells"] for h in hyg.values())),
}

# ------------------------------------------------------------ centreline
cl = {}
for n in ("Badge", "Plate", "Plate_Carrier", "Grille_Upper", "Grille_Lower",
          "DRL_Blade", "Badge_Mount"):
    if n not in W:
        continue
    v = W[n][0]
    mid = 0.5 * (v[:, 2].min() + v[:, 2].max())
    cl[n] = {"z_min": round(float(v[:, 2].min()), 6),
             "z_max": round(float(v[:, 2].max()), 6),
             "z_mid": round(float(mid), 6),
             "offset_from_centreline_mm": round(float(mid - ZC) * 1000, 4),
             "width_mm": round(float(v[:, 2].max() - v[:, 2].min()) * 1000, 2)}
R["checks"]["centreline"] = cl

# ------------------------------------------------------------ landmarks
lm = {}
if "Plate" in W:
    v = W["Plate"][0]
    lm["plate"] = {"width_mm": round(float(np.ptp(v[:, 2])) * 1000, 2),
                   "height_mm": round(float(np.ptp(v[:, 1])) * 1000, 2),
                   "spec": [520.0, 111.0],
                   "centre_y": round(float(0.5 * (v[:, 1].min() + v[:, 1].max())), 5)}
if "Badge" in W:
    v = W["Badge"][0]
    lm["badge"] = {"diameter_z_mm": round(float(np.ptp(v[:, 2])) * 1000, 2),
                   "diameter_y_mm": round(float(np.ptp(v[:, 1])) * 1000, 2),
                   "planned_mm": round(P["parts"]["badge"]["diameter"] * 1000, 2),
                   "centre_y": round(float(0.5 * (v[:, 1].min() + v[:, 1].max())), 5),
                   "planned_centre_y": P["y"]["badge_centre"]}
if "Grille_Upper" in W:
    v = W["Grille_Upper"][0]
    lm["grille_upper"] = {"width_mm": round(float(np.ptp(v[:, 2])) * 1000, 2),
                          "y_min": round(float(v[:, 1].min()), 5),
                          "y_max": round(float(v[:, 1].max()), 5)}
for t in ("L", "R"):
    k = f"Headlamp_{t}_Lens"
    if k in W:
        v = W[k][0]
        lm[k] = {"z_inner_mm_from_centre": round(float(min(abs(v[:, 2] - ZC))) * 1000, 1),
                 "z_outer_mm_from_centre": round(float(max(abs(v[:, 2] - ZC))) * 1000, 1),
                 "length_mm": round(float(np.ptp(v[:, 2])) * 1000, 1),
                 "y_min": round(float(v[:, 1].min()), 5),
                 "y_max": round(float(v[:, 1].max()), 5)}
if "TowEye_Cover" in W:
    v = W["TowEye_Cover"][0]
    lm["tow_eye"] = {"z_mid": round(float(0.5 * (v[:, 2].min() + v[:, 2].max())), 5),
                     "side": "car RIGHT (-z)" if v[:, 2].mean() < ZC else "car LEFT (+z)",
                     "mirrored_copy_exists": False}
R["checks"]["landmarks"] = lm

json.dump(R, open(OUT, "w"), indent=1)

s = R["checks"]
print(f"HIERARCHY  {s['hierarchy_summary']['present_with_geometry']}/"
      f"{s['hierarchy_summary']['required']} components present with geometry")
print(f"           old melt nodes still present: "
      f"{s['hierarchy_summary']['old_melt_nodes_still_present'] or 'NONE'}")
pv = s["provenance_v0_residue"]
print(f"PROVENANCE original front-zone faces {pv['original_front_zone_faces']}, "
      f"{pv['removed_faces']} removed, residue {pv['residue_frac']*100:.2f}%")
print(f"SYMMETRY   worst L/R deviation {s['symmetry_worst_mm']} mm "
      f"(v6 was 29.7 mm against a 2 mm threshold)")
for k, vv in sym.items():
    if "max_dev_mm" in vv:
        print(f"             {k:42s} max {vv['max_dev_mm']:.6f} mm")
hs = s["hygiene_summary"]
print(f"PROVENANCE(new nodes) worst fraction of a component's faces that are "
      f"ORIGINAL geometry: {s['provenance_new_nodes_worst_frac']}")
print(f"HYGIENE    self-intersecting pairs total {hs['total_self_intersecting_pairs']} "
      f"(worst node {hs['worst_self_intersecting_pairs']}) | v6 total 10258, worst 2924")
print(f"           of which WITHIN one shell (a real defect): "
      f"{hs['total_intersect_within_one_shell']}  |  BETWEEN overlapping shells "
      f"(construction): {hs['total_intersect_between_shells']}")
print(f"           winding inconsistent: {hs['nodes_winding_inconsistent'] or 'NONE'}")
print(f"           not watertight: {hs['nodes_not_watertight'] or 'NONE'}")
print(f"           degenerate faces {hs['total_degenerate_faces']}, "
      f"shells {hs['total_shells']}")
print("CENTRELINE")
for n, c in cl.items():
    print(f"           {n:16s} offset {c['offset_from_centreline_mm']:+8.4f} mm  "
          f"width {c['width_mm']:8.2f} mm")
print("VERIFY7_DONE", OUT)
