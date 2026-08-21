#!/usr/bin/env python3
"""verify_front_gate.py -- INDEPENDENT verification of a Gate 3 v6 front rebuild.

The owner's spec: "The editor cannot self-certify without a fresh exported-GLB
test."  This file is that test.  It is written by the verifier, never by the
builder, it reads exported GLBs and never writes one, and every check it makes
has a matching negative control in `selftest` that proves the check can FAIL.

WHAT IT MEASURES
  hierarchy   every required component is a real node with real geometry
  hygiene     non-manifold / duplicate / zero-area / flipped / loose / scale
  intersect   self-intersections and inter-object intersections (exact tri-tri)
  clearance   real millimetre gaps between the front components
  symmetry    L/R deviation about the FITTED vehicle centreline
  fascia      the decisive test: is the old melt gone, or hidden behind parts?

--------------------------------------------------------------------------
THE HIDDEN-FASCIA TEST -- HYPOTHESIS AND FALSIFICATION, WRITTEN BEFORE THE
PROBE WAS BUILT (this project has a documented case of a probe that could only
confirm its author; see CLAUDE.md, the white-dot saga)
--------------------------------------------------------------------------
H0 (the builder's claim): the broken original fascia was DELETED and replaced.
H1 (the rival): the new parts were laid OVER the broken original, which is
    still in the file, hidden behind them.  This is exactly how v5 failed.

Probe: fire a dense grid of rays at the nose along +X (the nose is at -X on
this file) and record EVERY surface each ray crosses, with the node that owns
it and the depth behind the first hit.

  OBSERVATION THAT PROVES H1 (melt still there):
    a ray whose FIRST hit is a constructed component is followed, within a
    short depth window (2 mm .. 250 mm), by a hit on ORIGINAL-SHELL geometry
    (carpaint / interior / glass / Lamp_Lens / Tyre_Rubber).  A nested second
    surface a few centimetres behind a new lens is the smoking gun.  A high
    percentage of such rays across the fascia = H1 confirmed.
  OBSERVATION THAT PROVES H0 (melt gone):
    behind the first hit there is nothing until the ray leaves the far side of
    the car (depth >> 250 mm), or nothing at all.

Two corroborating measurements, because one probe is not evidence:
  * V0-RESIDUE: what fraction of the ORIGINAL front-zone shell triangles (from
    GOLF_V0_ORIGINAL_LOCKED.glb, matched by triangle centroid to 0.1 mm) still
    exist in the file under test.  Deletion of the old fascia must show up as a
    drop in this number.  It is a face test, not a vertex test: v5 kept every
    original vertex and only dropped faces, so a vertex test would read 100%
    on both and prove nothing.
  * COMPONENTS-OFF render: hide every constructed node and look at what is
    left in the aperture.  If the melt is gone there is a hole.

A note on what would make the probe itself wrong: the shell is ONE surface
split by material label, so a ray crossing the car will always hit the far
side of the body eventually.  That is why the depth WINDOW matters and why the
window is reported alongside the number.

RUN
    python3 verify_front_gate.py measure CAR.glb --v0 V0.glb --out out.json
    python3 verify_front_gate.py selftest --out selftest.json
"""
import argparse
import json
import os
import struct
import sys
import time

import numpy as np
import trimesh
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tri_intersect import broadphase, tri_tri_pairs, intersect_count  # noqa: E402

# The six labels that make up the ORIGINAL generated shell. Anything else in
# the node list is a constructed component.
SHELL_NODES = {"carpaint", "interior", "glass", "Tyre_Rubber", "Rim_Alloy", "Lamp_Lens"}

# Required component inventory for Gate 3 v6 (owner's Step 3 list).
REQUIRED = [
    "Headlamp_L_Housing", "Headlamp_L_Lens", "Headlamp_L_DRL", "Headlamp_L_Internal",
    "Headlamp_R_Housing", "Headlamp_R_Lens", "Headlamp_R_DRL", "Headlamp_R_Internal",
    "Grille_Upper", "Badge_Mount", "Badge", "Bumper_Front",
    "Plate_Carrier", "Plate", "Grille_Lower", "Intake_L", "Intake_R", "Splitter_Front",
]
# Left/right pairs whose symmetry is measured about the fitted centreline.
LR_PAIRS = [("Headlamp_L_Housing", "Headlamp_R_Housing"),
            ("Headlamp_L_Lens", "Headlamp_R_Lens"),
            ("Headlamp_L_DRL", "Headlamp_R_DRL"),
            ("Headlamp_L_Internal", "Headlamp_R_Internal"),
            ("Intake_L", "Intake_R")]
# Components that must straddle the centreline.
CENTRED = ["Badge", "Badge_Mount", "Plate", "Plate_Carrier", "Grille_Upper",
           "Grille_Lower", "Bumper_Front", "Splitter_Front"]

MM = 1000.0


# ------------------------------------------------------------------ loading
def gltf_json(path):
    """The glTF JSON chunk, read straight out of the GLB container."""
    with open(path, "rb") as fh:
        head = fh.read(20)
        if head[:4] != b"glTF":
            raise ValueError(f"{path} is not a binary glTF")
        jlen = struct.unpack("<I", head[12:16])[0]
        return json.loads(fh.read(jlen))


class Car:
    """A loaded GLB with node transforms APPLIED to the vertices.

    CLAUDE.md: downstream stages bake instance transforms, so a node
    translation may read 0.0000 on a perfectly correct file.  Everything here
    is measured from TRANSFORMED VERTICES.
    """

    def __init__(self, path):
        self.path = path
        self.gltf = gltf_json(path)
        sc = trimesh.load(path, force="scene")
        self.nodes = {}          # node name -> dict(V, F, T, geom)
        for nname in sc.graph.nodes_geometry:
            T, gname = sc.graph[nname]
            g = sc.geometry[gname]
            V = trimesh.transform_points(np.asarray(g.vertices, np.float64), T)
            self.nodes[nname] = {
                "V": V, "F": np.asarray(g.faces, np.int64), "T": np.asarray(T),
                "geom": gname,
                "normals": (np.asarray(g.vertex_normals)
                            if "vertex_normals" in g._cache.cache or True else None),
            }
        del sc
        self.names = sorted(self.nodes)
        self.built = [n for n in self.names if n not in SHELL_NODES]
        self.shell = [n for n in self.names if n in SHELL_NODES]

    def concat(self):
        """One mesh of everything, plus a per-face owner index."""
        Vs, Fs, own, off = [], [], [], 0
        for i, n in enumerate(self.names):
            d = self.nodes[n]
            Vs.append(d["V"])
            Fs.append(d["F"] + off)
            own.append(np.full(len(d["F"]), i, np.int32))
            off += len(d["V"])
        return (np.vstack(Vs), np.vstack(Fs), np.concatenate(own))

    def bounds(self):
        A = np.vstack([d["V"] for d in self.nodes.values()])
        return A.min(0), A.max(0)


def tri_area(V, F):
    T = V[F]
    return 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)


def weld(V, F, q=1e-6):
    """Coordinate-quantised weld. trimesh keeps split verts when normals or UVs
    differ, and a GLB stores unique verts per face -- a naive component count
    then reads hundreds of thousands of 'components' for one surface
    (CLAUDE.md, label_bench)."""
    key = np.round(V / q).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    return inv[F]


# ------------------------------------------------------------ 1. hierarchy
def check_hierarchy(car, required=REQUIRED):
    """Owner's rule: never claim a part exists separately unless the GLB
    hierarchy proves it. Reads the glTF node/mesh/accessor tables directly."""
    g = car.gltf
    acc = g.get("accessors", [])
    by_name = {}
    for ni, n in enumerate(g.get("nodes", [])):
        nm = n.get("name")
        rec = {"node_index": ni, "has_mesh": "mesh" in n,
               "children": len(n.get("children", [])),
               "matrix": n.get("matrix"), "translation": n.get("translation"),
               "rotation": n.get("rotation"), "scale": n.get("scale")}
        if "mesh" in n:
            m = g["meshes"][n["mesh"]]
            prims = []
            for p in m["primitives"]:
                a = p["attributes"]
                prims.append({
                    "vertices": acc[a["POSITION"]]["count"] if "POSITION" in a else 0,
                    "indices": acc[p["indices"]]["count"] if "indices" in p else 0,
                    "has_NORMAL": "NORMAL" in a,
                    "material": (g["materials"][p["material"]].get("name")
                                 if "material" in p else None),
                    "mode": p.get("mode", 4),
                })
            rec["mesh_index"] = n["mesh"]
            rec["mesh_name"] = m.get("name")
            rec["primitives"] = prims
            rec["vertices"] = sum(p["vertices"] for p in prims)
            rec["faces"] = sum(p["indices"] // 3 for p in prims)
        by_name.setdefault(nm, []).append(rec)

    # a name used by more than one node, or a mesh shared by two nodes, is not
    # a separately selectable part
    mesh_users = {}
    for ni, n in enumerate(g.get("nodes", [])):
        if "mesh" in n:
            mesh_users.setdefault(n["mesh"], []).append(n.get("name"))

    out = {"present": {}, "missing": [], "empty": [], "shared_mesh": [],
           "node_count": len(g.get("nodes", [])),
           "all_node_names": [n.get("name") for n in g.get("nodes", [])]}
    for want in required:
        recs = by_name.get(want)
        if not recs:
            out["missing"].append(want)
            continue
        r = recs[0]
        ok_geom = r.get("faces", 0) > 0 and r.get("vertices", 0) > 0
        shared = len(mesh_users.get(r.get("mesh_index", -1), [])) > 1
        if not ok_geom:
            out["empty"].append(want)
        if shared:
            out["shared_mesh"].append(want)
        out["present"][want] = {
            "node_index": r["node_index"], "mesh_name": r.get("mesh_name"),
            "vertices": r.get("vertices", 0), "faces": r.get("faces", 0),
            "has_NORMAL": all(p["has_NORMAL"] for p in r.get("primitives", [])),
            "material": [p["material"] for p in r.get("primitives", [])],
            "duplicate_nodes_with_name": len(recs), "mesh_shared": shared,
        }
    out["pass"] = (not out["missing"] and not out["empty"]
                   and not out["shared_mesh"]
                   and all(v["has_NORMAL"] for v in out["present"].values()))
    return out


# -------------------------------------------------------------- 2. hygiene
def hygiene_one(V, F, T=None, area_eps=1e-10):
    """Topology/hygiene facts for one node's geometry."""
    r = {"vertices": int(len(V)), "faces": int(len(F))}
    if len(F) == 0:
        return r
    a = tri_area(V, F)
    r["zero_area_faces"] = int((a <= area_eps).sum())
    r["min_area_mm2"] = float(a.min() * 1e6)

    Fw = weld(V, F)
    r["welded_vertices"] = int(Fw.max() + 1) if len(Fw) else 0
    # duplicate faces: same welded vertex set
    keys = np.sort(Fw, axis=1)
    uniq, cnt = np.unique(keys, axis=0, return_counts=True)
    r["duplicate_faces"] = int((cnt - 1).sum())
    r["degenerate_index_faces"] = int((keys[:, 0] == keys[:, 1]).sum()
                                      + (keys[:, 1] == keys[:, 2]).sum())

    # edges on the welded topology
    E = np.sort(np.vstack([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), axis=1)
    ue, ec = np.unique(E, axis=0, return_counts=True)
    r["boundary_edges"] = int((ec == 1).sum())
    r["nonmanifold_edges"] = int((ec > 2).sum())
    r["edges"] = int(len(ue))

    # connected components on welded topology (union-find over edges)
    nv = int(Fw.max() + 1)
    parent = np.arange(nv)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for u, v in ue:
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv
    roots = np.array([find(i) for i in range(nv)])
    used = np.unique(Fw)
    labs, counts = np.unique(roots[used], return_counts=True)
    r["components"] = int(len(labs))
    r["largest_component_pct"] = float(100.0 * counts.max() / counts.sum())
    r["small_components"] = int((counts < max(4, 0.001 * counts.sum())).sum())

    # winding / flipped normals
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    try:
        r["winding_consistent"] = bool(m.is_winding_consistent)
        r["watertight"] = bool(m.is_watertight)
        r["volume_cm3"] = float(abs(m.volume) * 1e6)
        r["volume_sign_negative"] = bool(m.is_watertight and m.volume < 0)
        # is_volume == watertight AND winding consistent AND positive volume.
        # This is the rigorous inversion test for a CLOSED part: a whole part
        # flipped inside-out stays winding-CONSISTENT and only shows up here.
        r["is_volume"] = bool(m.is_volume)
    except Exception as e:                                   # pragma: no cover
        r["winding_error"] = str(e)

    # Informational only, NOT a gate: fraction of faces whose normal points
    # back toward the part centroid. On the V5 lens solids this read 44.89%
    # and those parts are not inverted -- a concave/bowl-shaped closed solid
    # legitimately has many faces pointing "inward" of its own centroid. The
    # centroid test is only sound for convex shapes, so the inversion verdict
    # is taken from is_volume / volume sign instead.
    if r.get("watertight"):
        Tv = V[F]
        n = np.cross(Tv[:, 1] - Tv[:, 0], Tv[:, 2] - Tv[:, 0])
        ln = np.linalg.norm(n, axis=1)
        good = ln > 1e-15
        n = n[good] / ln[good][:, None]
        c = Tv[good].mean(1) - V.mean(0)
        cl = np.linalg.norm(c, axis=1)
        ok = cl > 1e-12
        r["inward_facing_pct"] = float(100.0 * np.mean(
            np.einsum("ij,ij->i", n[ok], c[ok] / cl[ok][:, None]) < 0))

    if T is not None:
        r["transform_identity"] = bool(np.allclose(T, np.eye(4), atol=1e-9))
        r["transform_det"] = float(np.linalg.det(T[:3, :3]))
        r["negative_scale"] = bool(np.linalg.det(T[:3, :3]) < 0)
    return r


def check_hygiene(car, which=None):
    out = {}
    for n in (which if which is not None else car.names):
        d = car.nodes[n]
        out[n] = hygiene_one(d["V"], d["F"], d["T"])
    return out


# --------------------------------------------------- 3. intersections/gaps
def self_intersections(V, F, eps=1e-6, cap=40_000_000):
    return intersect_count(V, F, V, F, share_verts=True, eps=eps, max_pairs=cap)


def pair_intersection(VA, FA, VB, FB, eps=1e-6, cap=40_000_000):
    return intersect_count(VA, FA, VB, FB, eps=eps, max_pairs=cap)


class _PQ:
    """Per-part mesh + proximity query + surface samples, built ONCE.

    The first version rebuilt a proximity tree for every pair, which is O(F) per
    build and dominated the clearance stage on a 27-component file. Nothing
    about the numbers changes -- only how many times the same tree is built.
    """

    def __init__(self, V, F, n=4000, seed=0):
        self.m = trimesh.Trimesh(vertices=V, faces=F, process=False)
        self.pq = trimesh.proximity.ProximityQuery(self.m)
        self.n = min(n, 20000)
        self.pts, _ = trimesh.sample.sample_surface(self.m, self.n, seed=seed)
        self.watertight = bool(self.m.is_watertight)


def gap_between(A, B):
    """Minimum surface-to-surface distance in mm; negative = interpenetration."""
    dAB = B.pq.signed_distance(A.pts)
    dBA = A.pq.signed_distance(B.pts)
    gapA = -dAB if B.watertight else np.abs(dAB)
    gapB = -dBA if A.watertight else np.abs(dBA)
    return {"gap_mm": round(float(min(gapA.min(), gapB.min())) * MM, 3),
            "samples_per_side": int(A.n),
            "A_watertight": A.watertight, "B_watertight": B.watertight}


def surface_gap_mm(VA, FA, VB, FB, n=4000, seed=0):
    """Minimum surface-to-surface distance, in mm, by dense surface sampling.

    Honest about its own resolution: the sample count is reported with the
    number.  Returns None when either side has no geometry.
    """
    if len(FA) == 0 or len(FB) == 0:
        return None
    mA = trimesh.Trimesh(vertices=VA, faces=FA, process=False)
    mB = trimesh.Trimesh(vertices=VB, faces=FB, process=False)
    rng = np.random.default_rng(seed)
    PA, _ = trimesh.sample.sample_surface(mA, min(n, 20000), seed=int(rng.integers(1 << 30)))
    PB, _ = trimesh.sample.sample_surface(mB, min(n, 20000), seed=int(rng.integers(1 << 30)))
    dAB = trimesh.proximity.ProximityQuery(mB).signed_distance(PA)
    dBA = trimesh.proximity.ProximityQuery(mA).signed_distance(PB)
    # signed_distance is +ve INSIDE for watertight meshes
    gapA = -dAB if mB.is_watertight else np.abs(dAB)
    gapB = -dBA if mA.is_watertight else np.abs(dBA)
    g = float(min(gapA.min(), gapB.min()) * MM)
    return {"gap_mm": round(g, 3), "samples_per_side": int(min(n, 20000)),
            "A_watertight": bool(mA.is_watertight), "B_watertight": bool(mB.is_watertight)}


def check_clearance(car, parts=None, max_pairs_report=400):
    parts = parts if parts is not None else car.built
    out = {"pairs": {}, "intersecting": [], "note": ""}
    pqc = {}
    # only pairs whose AABBs are within 60 mm of each other are worth measuring
    box = {p: (car.nodes[p]["V"].min(0), car.nodes[p]["V"].max(0)) for p in parts
           if len(car.nodes[p]["F"])}
    keys = sorted(box)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            (lo1, hi1), (lo2, hi2) = box[a], box[b]
            sep = np.maximum(lo1 - hi2, lo2 - hi1).max()
            # neighbouring parts get a 60 mm window; the owner's named
            # inventory (lamp/grille/bumper/badge/plate/splitter) gets 150 mm so
            # the report can quote a real gap for the pairs that were asked for
            # rather than silently omitting them as "far apart"
            lim = 0.15 if (a in REQUIRED and b in REQUIRED) else 0.06
            if sep > lim:
                continue
            A, B = car.nodes[a], car.nodes[b]
            ix = pair_intersection(A["V"], A["F"], B["V"], B["F"])
            for nm, d in ((a, A), (b, B)):
                if nm not in pqc:
                    pqc[nm] = _PQ(d["V"], d["F"])
            gap = gap_between(pqc[a], pqc[b])
            rec = {"aabb_separation_mm": round(float(sep) * MM, 3), **ix}
            if gap:
                rec.update(gap)
            out["pairs"][f"{a}|{b}"] = rec
            if ix["intersecting_pairs"] > 0:
                out["intersecting"].append(f"{a}|{b}")
            if len(out["pairs"]) >= max_pairs_report:
                out["note"] = "pair cap reached"
                return out
    return out


# -------------------------------------------------------------- 4. symmetry
def fit_centreline(car, sample=30000, seed=0):
    """Evidence for the vehicle centreline -- and an honest verdict on whether
    the geometry can supply one at all.

    FIRST ATTEMPT (kept in the record because it was WRONG): a golden-section
    minimisation of the mirrored nearest-neighbour distance.  It returned
    c = -24.4 mm with a 24 mm residual.  Scanning the cost curve showed there
    is NO interior minimum on this shell -- the cost falls monotonically to the
    edge of the bracket, so the "fit" was reading the bracket, not the car.
    The residual is ~15 mm everywhere: this generated shell simply is not
    mirror-symmetric at millimetre scale.

    The wheel landmarks cannot rescue it either: on V0 the front rims give
    +26.4 mm and the rears -65.4 mm, and CLAUDE.md records that on this car
    `Rim_Alloy` and `Tyre_Rubber` are bound to bumper faces, not to wheels.

    So the centreline USED is the authored frame z = 0, corroborated by the
    bounding-box mid-plane.  What that supports is a statement about whether
    the BUILDER centred the constructed parts in the frame they were authored
    in -- which is the gate's actual question.  It does not support a claim
    about the physical vehicle's centreline, and none is made.
    """
    V = np.vstack([car.nodes[n]["V"] for n in car.shell if len(car.nodes[n]["F"])])
    tree = cKDTree(V)
    rng = np.random.default_rng(seed)
    q = V[rng.choice(len(V), size=min(sample, len(V)), replace=False)]
    scan = {}
    for c in np.linspace(-0.030, 0.030, 13):
        M = q.copy()
        M[:, 2] = 2 * c - M[:, 2]
        d, _ = tree.query(M, k=1)
        scan[round(float(c) * MM, 1)] = round(float(np.median(d)) * MM, 3)
    ks = sorted(scan)
    vals = [scan[k] for k in ks]
    interior_min = bool(0 < int(np.argmin(vals)) < len(vals) - 1)
    return {"used_centreline_z": 0.0,
            "basis": "authored frame z=0 (see docstring); NOT a symmetry fit",
            "bbox_mid_z_mm": round(float(0.5 * (V[:, 2].min() + V[:, 2].max())) * MM, 4),
            "shell_vertex_mean_z_mm": round(float(V[:, 2].mean()) * MM, 3),
            "mirror_residual_scan_mm": scan,
            "scan_has_interior_minimum": interior_min,
            "scan_verdict": ("a symmetry fit on this shell is not usable: "
                             "no interior minimum, residual ~15 mm everywhere")
                            if not interior_min else "interior minimum found",
            "samples": int(len(q))}


def mirror_deviation_mm(VL, FL, VR, FR, c, n=4000, seed=0):
    """Deviation between a LEFT part mirrored about z=c and the RIGHT part.

    Measured as point-to-SURFACE distance in both directions (a vertex-to-
    vertex distance would read the tessellation, not the shape).
    """
    if len(FL) == 0 or len(FR) == 0:
        return None
    ML = trimesh.Trimesh(vertices=VL.copy(), faces=FL, process=False)
    ML.vertices[:, 2] = 2 * c - ML.vertices[:, 2]
    ML.invert()                      # mirroring flips winding; restore it
    MR = trimesh.Trimesh(vertices=VR, faces=FR, process=False)
    rng = np.random.default_rng(seed)
    PL, _ = trimesh.sample.sample_surface(ML, min(n, 20000), seed=int(rng.integers(1 << 30)))
    PR, _ = trimesh.sample.sample_surface(MR, min(n, 20000), seed=int(rng.integers(1 << 30)))
    d1 = trimesh.proximity.ProximityQuery(MR).on_surface(PL)[1]
    d2 = trimesh.proximity.ProximityQuery(ML).on_surface(PR)[1]
    d = np.concatenate([d1, d2]) * MM
    # A point-to-SURFACE distance is blind to a rigid slide ALONG the surface:
    # a box displaced 5 mm sideways still has most of its points 0.000 mm from
    # the other box's skin (proved in selftest -- the median read 0.0). So the
    # reported deviation is the MAXIMUM, and a centroid/bbox delta is carried
    # alongside because that catches a pure translation directly.
    aL = tri_area(ML.vertices, ML.faces)
    aR = tri_area(MR.vertices, MR.faces)
    cL = (ML.vertices[ML.faces].mean(1) * aL[:, None]).sum(0) / aL.sum()
    cR = (MR.vertices[MR.faces].mean(1) * aR[:, None]).sum(0) / aR.sum()
    bL = 0.5 * (ML.vertices.min(0) + ML.vertices.max(0))
    bR = 0.5 * (MR.vertices.min(0) + MR.vertices.max(0))
    eL = ML.vertices.max(0) - ML.vertices.min(0)
    eR = MR.vertices.max(0) - MR.vertices.min(0)
    return {"median_mm": round(float(np.median(d)), 4),
            "p95_mm": round(float(np.percentile(d, 95)), 4),
            "max_mm": round(float(d.max()), 4),
            "centroid_delta_mm": [round(float(v) * MM, 4) for v in (cR - cL)],
            "bbox_centre_delta_mm": [round(float(v) * MM, 4) for v in (bR - bL)],
            "extent_delta_mm": [round(float(v) * MM, 4) for v in (eR - eL)],
            "faces_L": int(len(ML.faces)), "faces_R": int(len(MR.faces)),
            "samples": int(len(d))}


def centre_offset_mm(V, F, c):
    if len(F) == 0:
        return None
    A = tri_area(V, F)
    cen = (V[F].mean(1) * A[:, None]).sum(0) / A.sum()
    lo, hi = V[:, 2].min(), V[:, 2].max()
    return {"area_centroid_z_offset_mm": round(float((cen[2] - c) * MM), 4),
            "bbox_mid_z_offset_mm": round(float((0.5 * (lo + hi) - c) * MM), 4),
            "z_extent_mm": round(float((hi - lo) * MM), 2)}


def _area_centroid(V, F):
    a = tri_area(V, F)
    return (V[F].mean(1) * a[:, None]).sum(0) / a.sum()


def check_symmetry(car, pairs=LR_PAIRS, centred=CENTRED):
    """Symmetry is reported as TWO separable numbers, because they fail for
    different reasons and a single blended figure hides both:

      SHAPE deviation   -- L mirrored about the plane that best pairs the two
                           parts (the midpoint of their centroids).  This is
                           independent of where the pair sits on the car, so a
                           centreline uncertainty cannot contaminate it.
      PLACEMENT offset  -- how far that pair-plane sits from the vehicle
                           centreline.  A perfectly matched pair mounted 6 mm
                           off-centre fails here and passes above.
    """
    fit = fit_centreline(car)
    c = fit["used_centreline_z"]
    out = {"fit": fit, "pairs": {}, "centred": {}}
    for l, r in pairs:
        if l in car.nodes and r in car.nodes and len(car.nodes[l]["F"]) and len(car.nodes[r]["F"]):
            L, R = car.nodes[l], car.nodes[r]
            zl = float(_area_centroid(L["V"], L["F"])[2])
            zr = float(_area_centroid(R["V"], R["F"])[2])
            c_pair = 0.5 * (zl + zr)
            shape = mirror_deviation_mm(L["V"], L["F"], R["V"], R["F"], c_pair)
            asbuilt = mirror_deviation_mm(L["V"], L["F"], R["V"], R["F"], c)
            out["pairs"][f"{l}|{r}"] = {
                "shape_deviation": shape,
                "as_built_about_vehicle_centreline": asbuilt,
                "pair_plane_z_mm": round(c_pair * MM, 4),
                "placement_offset_from_centreline_mm": round((c_pair - c) * MM, 4),
                "centroid_z_L_mm": round(zl * MM, 3), "centroid_z_R_mm": round(zr * MM, 3)}
        else:
            out["pairs"][f"{l}|{r}"] = "MISSING"
    for n in centred:
        out["centred"][n] = (centre_offset_mm(car.nodes[n]["V"], car.nodes[n]["F"], c)
                             if n in car.nodes else "MISSING")
    return out


# -------------------------------------------------------- 5. hidden fascia
def check_hidden_fascia(car, zone_m=0.65, pitch=0.006, win=(0.002, 0.250), v0=None,
                        tol=1e-4):
    """See the hypothesis block at the top of this file.

    Fires rays along +X (nose is at -X) over the front of the car and records
    every surface crossed.  Classifies each ray by what it hits FIRST and what
    lies behind that within the depth window.
    """
    V, F, own = car.concat()
    # PROVENANCE, not naming. A node called `Bumper_Front` that is actually the
    # original melt cut out and renamed would be counted as a "constructed
    # component" by any name-based rule, and melt hidden behind it would then
    # be invisible to this probe. So when V0 is supplied, every face is tagged
    # by whether that exact triangle exists in the original file, and the
    # nesting test is run on BOTH classifications.
    orig_face = None
    if v0 is not None:
        C0 = np.vstack([v0.nodes[n]["V"][v0.nodes[n]["F"]].mean(1)
                        for n in v0.names if len(v0.nodes[n]["F"])])
        cF = V[F].mean(1)
        dd, _ = cKDTree(C0).query(cF, k=1, distance_upper_bound=tol)
        orig_face = np.isfinite(dd)
    mesh = trimesh.Trimesh(vertices=V, faces=F, process=False)
    inter = trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
    lo, hi = car.bounds()
    XMIN = float(lo[0])
    built_idx = {i for i, n in enumerate(car.names) if n in car.built}

    # The grid must cover every constructed component, not a hard-coded window:
    # a splitter that sits below y=0.32 or a bonnet lead above y=1.00 would
    # otherwise be sampled partially or not at all, and a probe that does not
    # look at a part cannot find melt behind it.
    y0, y1, z0, z1 = 0.32, 1.00, -0.82, 0.82
    for n in car.built:
        d = car.nodes[n]
        if len(d["F"]) == 0:
            continue
        y0 = min(y0, float(d["V"][:, 1].min()) - 0.01)
        y1 = max(y1, float(d["V"][:, 1].max()) + 0.01)
        z0 = min(z0, float(d["V"][:, 2].min()) - 0.01)
        z1 = max(z1, float(d["V"][:, 2].max()) + 0.01)
    ys = np.arange(y0, y1, pitch)
    zs = np.arange(z0, z1, pitch)
    ZZ, YY = np.meshgrid(zs, ys)
    N = ZZ.size
    org = np.stack([np.full(N, XMIN - 0.5), YY.ravel(), ZZ.ravel()], 1)
    dr = np.tile([1.0, 0.0, 0.0], (N, 1))
    loc, iray, itri = inter.intersects_location(org, dr, multiple_hits=True)
    depth = loc[:, 0] - (XMIN - 0.5)
    owner = own[itri]

    order = np.lexsort((depth, iray))
    iray, depth, owner = iray[order], depth[order], owner[order]
    starts = np.searchsorted(iray, np.arange(N), side="left")
    ends = np.searchsorted(iray, np.arange(N), side="right")

    first_face = np.full(N, -1, np.int64)
    nested_orig = np.zeros(N, bool)     # ORIGINAL face behind a NEW first hit
    nested_orig_depth = np.full(N, np.nan)
    new_first = np.zeros(N, bool)
    first_owner = np.full(N, -1, np.int32)
    nested = np.zeros(N, bool)          # shell surface right behind a component
    nested_depth = np.full(N, np.nan)
    nested_owner = np.full(N, -1, np.int32)
    comp_first = np.zeros(N, bool)
    n_hits = ends - starts
    face_sorted = itri[order]
    for k in range(N):
        s, e = starts[k], ends[k]
        if s == e:
            continue
        first_owner[k] = owner[s]
        first_face[k] = face_sorted[s]
        if orig_face is not None and not orig_face[face_sorted[s]]:
            new_first[k] = True
            d0 = depth[s]
            for t in range(s + 1, e):
                dd2 = depth[t] - d0
                if dd2 < win[0]:
                    continue
                if dd2 > win[1]:
                    break
                if orig_face[face_sorted[t]]:
                    nested_orig[k] = True
                    nested_orig_depth[k] = dd2
                    break
        if owner[s] in built_idx:
            comp_first[k] = True
            d0 = depth[s]
            for t in range(s + 1, e):
                dd = depth[t] - d0
                if dd < win[0]:
                    continue
                if dd > win[1]:
                    break
                if owner[t] not in built_idx:
                    nested[k] = True
                    nested_depth[k] = dd
                    nested_owner[k] = owner[t]
                    break

    # Depth stratification. A hit 220 mm behind an OPEN intake is the inner
    # wing -- real structure, not a duplicated skin. A hit 3-60 mm behind a new
    # lens is a second fascia surface. Reporting one blended percentage would
    # merge the two and over-claim, so the bands are reported separately and
    # the gate is judged on the SHALLOW band.
    bands = [(2, 10), (10, 30), (30, 60), (60, 120), (120, 250)]
    nd = nested_depth[nested] * MM
    band_counts = {f"{a}-{b}mm": int(((nd >= a) & (nd < b)).sum()) for a, b in bands}
    shallow = int((nd < 60).sum())

    res = {
        "rays": int(N), "grid_pitch_mm": pitch * MM,
        "zone": {"x_from_nose_m": zone_m,
                 "y": [round(y0, 4), round(y1, 4)], "z": [round(z0, 4), round(z1, 4)],
                 "note": "grid auto-expanded to cover every constructed component"},
        "depth_window_mm": [win[0] * MM, win[1] * MM],
        "rays_hitting_anything": int((n_hits > 0).sum()),
        "rays_component_first": int(comp_first.sum()),
        "rays_component_first_with_shell_behind": int(nested.sum()),
        "nested_pct_of_component_rays": (round(100.0 * nested.sum() / max(1, comp_first.sum()), 2)),
        "nested_depth_bands": band_counts,
        "shallow_nested_rays_under_60mm": shallow,
        "shallow_nested_pct": round(100.0 * shallow / max(1, comp_first.sum()), 2),
        "nested_depth_mm": ({"p5": round(float(np.nanpercentile(nested_depth, 5)) * MM, 1),
                             "median": round(float(np.nanmedian(nested_depth)) * MM, 1),
                             "p95": round(float(np.nanpercentile(nested_depth, 95)) * MM, 1)}
                            if nested.any() else None),
    }
    # who is the hidden surface
    if nested.any():
        u, cnt = np.unique(nested_owner[nested], return_counts=True)
        res["hidden_surface_owners"] = {car.names[int(a)]: int(b)
                                        for a, b in sorted(zip(u, cnt), key=lambda t: -t[1])}
    # per-component breakdown
    per = {}
    for i, n in enumerate(car.names):
        m = comp_first & (first_owner == i)
        if m.sum() == 0:
            continue
        shallow_m = nested[m] & (nested_depth[m] * MM < 60)
        per[n] = {"rays_first": int(m.sum()),
                  "shell_behind_pct": round(100.0 * nested[m].mean(), 2),
                  # the number that separates a DUPLICATED SKIN from real
                  # structure seen through an opening: only a surface within
                  # 60 mm of the new one is a second fascia
                  "shell_behind_under60mm_pct": round(100.0 * shallow_m.mean(), 2),
                  "shell_behind_under60mm_rays": int(shallow_m.sum())}
    # THE INVERSE DEFECT: a constructed part hidden BEHIND surviving melt. If
    # the old fascia was left in place, some new components sit behind it and
    # are never the first surface a ray meets. Measured inside each component's
    # own (y,z) footprint, so it cannot be diluted by the rest of the car.
    yv, zv = YY.ravel(), ZZ.ravel()
    is_built_first = np.isin(first_owner, list(built_idx))
    for i, n in enumerate(car.names):
        if n not in car.built:
            continue
        Vn = car.nodes[n]["V"]
        if len(car.nodes[n]["F"]) == 0:
            continue
        fp = ((yv >= Vn[:, 1].min()) & (yv <= Vn[:, 1].max())
              & (zv >= Vn[:, 2].min()) & (zv <= Vn[:, 2].max()))
        rays_hit_n = np.zeros(N, bool)
        rays_hit_n[np.unique(iray[owner == i])] = True
        buried = fp & rays_hit_n & ~is_built_first
        rec = per.setdefault(n, {"rays_first": 0, "shell_behind_pct": 0.0})
        rec["footprint_rays"] = int(fp.sum())
        rec["rays_reaching_part"] = int((fp & rays_hit_n).sum())
        rec["buried_behind_shell_rays"] = int(buried.sum())
        rec["buried_pct_of_part_rays"] = round(
            100.0 * buried.sum() / max(1, (fp & rays_hit_n).sum()), 2)
    res["per_component"] = dict(sorted(per.items(), key=lambda kv: -kv[1]["rays_first"]))
    # what shell geometry still lives in front of everything
    shell_first = {}
    for i, n in enumerate(car.names):
        if n in car.built:
            continue
        c = int(((first_owner == i)).sum())
        if c:
            shell_first[n] = c
    res["shell_first_hit_rays"] = shell_first

    if orig_face is not None:
        ndo = nested_orig_depth[nested_orig] * MM
        res["by_provenance"] = {
            "note": ("classified by whether each triangle exists in V0, so a "
                     "renamed piece of the original melt cannot pass as new"),
            "faces_in_file": int(len(F)),
            "faces_matching_V0": int(orig_face.sum()),
            "rays_new_surface_first": int(new_first.sum()),
            "rays_with_ORIGINAL_behind_a_NEW_surface": int(nested_orig.sum()),
            "pct": round(100.0 * nested_orig.sum() / max(1, new_first.sum()), 2),
            "shallow_under_60mm": int((ndo < 60).sum()) if nested_orig.any() else 0,
            "shallow_pct": (round(100.0 * (ndo < 60).sum() / max(1, new_first.sum()), 2)
                            if nested_orig.any() else 0.0),
            "depth_bands_mm": ({f"{a}-{b}mm": int(((ndo >= a) & (ndo < b)).sum())
                                for a, b in bands} if nested_orig.any() else {}),
        }
    return res


def v0_residue(car, v0, zone=0.65, tol=1e-4):
    """Fraction of the ORIGINAL front-zone triangles still present ANYWHERE in
    the file, and which node holds each survivor.

    Matched by triangle CENTROID to `tol` metres.

    TWO TRAPS THIS IS BUILT AROUND, both of which would give a wrong answer in
    the DANGEROUS direction (reporting deletion that did not happen):
      * A VERTEX test proves nothing here -- v5 kept every original vertex and
        deleted only faces, so vertex retention reads 100% on both.
      * A PER-LABEL test would be defeated by simply MOVING the old melt into a
        node called `Bumper_Front`. The melt would be renamed, not removed, and
        a same-label comparison would score it as deleted. So the match is
        against the union of EVERY face in the target file, and the owning node
        of each survivor is reported. `relocated` counts survivors that changed
        node -- that number is the rename-not-remove signature.
    """
    lo, _ = v0.bounds()
    XMIN = float(lo[0])
    C1, own1, names1 = [], [], car.names
    for i, n in enumerate(names1):
        d = car.nodes[n]
        if len(d["F"]) == 0:
            continue
        c = d["V"][d["F"]].mean(1)
        m = c[:, 0] < XMIN + zone
        C1.append(c[m])
        own1.append(np.full(int(m.sum()), i, np.int32))
    if C1:
        C1 = np.vstack(C1)
        own1 = np.concatenate(own1)
        tree = cKDTree(C1)
    else:
        C1, own1, tree = np.zeros((0, 3)), np.zeros(0, np.int32), None

    out = {"zone_x_max": XMIN + zone, "tol_mm": tol * MM,
           "target_front_faces_total": int(len(C1)), "per_label": {}}
    tot0 = tot1 = reloc = 0
    holders = {}
    for n in v0.shell:
        V0, F0 = v0.nodes[n]["V"], v0.nodes[n]["F"]
        c0 = V0[F0].mean(1)
        m0 = c0[:, 0] < XMIN + zone
        if m0.sum() == 0:
            continue
        if tree is None:
            kept, hits = 0, np.zeros(0, np.int32)
        else:
            d, idx = tree.query(c0[m0], k=1, distance_upper_bound=tol)
            ok = np.isfinite(d)
            kept = int(ok.sum())
            hits = own1[idx[ok]]
        per_node = {}
        for a, b in zip(*np.unique(hits, return_counts=True)):
            per_node[names1[int(a)]] = int(b)
            holders[names1[int(a)]] = holders.get(names1[int(a)], 0) + int(b)
        moved = kept - per_node.get(n, 0)
        reloc += moved
        out["per_label"][n] = {"v0_front_faces": int(m0.sum()), "retained": kept,
                               "retained_pct": round(100.0 * kept / m0.sum(), 2),
                               "now_owned_by": dict(sorted(per_node.items(),
                                                           key=lambda kv: -kv[1])),
                               "relocated_to_other_node": int(moved)}
        tot0 += int(m0.sum())
        tot1 += kept
    out["v0_front_faces_total"] = tot0
    out["retained_total"] = tot1
    out["retained_pct_total"] = round(100.0 * tot1 / max(1, tot0), 2)
    out["relocated_total"] = reloc
    out["survivors_by_holding_node"] = dict(sorted(holders.items(), key=lambda kv: -kv[1]))
    return out


def origin_audit(car, v0, tol=1e-4):
    """Per NODE of the target: what share of its faces are ORIGINAL V0 faces?

    This is the decisive test for "is this part constructed, or is it the old
    melt under a new name".  A genuinely rebuilt component scores ~0%.  A node
    that is simply the original geometry relabelled scores ~100%.
    """
    C0 = []
    for n in v0.names:
        d = v0.nodes[n]
        if len(d["F"]):
            C0.append(d["V"][d["F"]].mean(1))
    C0 = np.vstack(C0)
    tree = cKDTree(C0)
    out = {}
    for n in car.names:
        d = car.nodes[n]
        if len(d["F"]) == 0:
            out[n] = {"faces": 0}
            continue
        c = d["V"][d["F"]].mean(1)
        dd, _ = tree.query(c, k=1, distance_upper_bound=tol)
        share = float(np.isfinite(dd).mean())
        out[n] = {"faces": int(len(c)), "faces_matching_V0": int(np.isfinite(dd).sum()),
                  "pct_original_geometry": round(100.0 * share, 2),
                  "verdict": ("INHERITED_ORIGINAL" if share > 0.9 else
                              "MIXED" if share > 0.02 else "CONSTRUCTED")}
    return out


# ------------------------------------------------------------------- driver
def measure(path, v0path=None, label=None, skip=()):
    t0 = time.time()
    car = Car(path)
    R = {"file": os.path.abspath(path), "label": label or os.path.basename(path),
         "bytes": os.path.getsize(path),
         "sha256": _sha(path),
         "nodes": car.names, "built_components": car.built,
         "shell_nodes": car.shell}
    lo, hi = car.bounds()
    R["bbox_m"] = {"min": [round(float(v), 5) for v in lo],
                   "max": [round(float(v), 5) for v in hi],
                   "L_x": round(float(hi[0] - lo[0]), 5),
                   "H_y": round(float(hi[1] - lo[1]), 5),
                   "W_z": round(float(hi[2] - lo[2]), 5)}
    if "hierarchy" not in skip:
        R["hierarchy"] = check_hierarchy(car)
    if "hygiene" not in skip:
        R["hygiene"] = check_hygiene(car)
    if "selfint" not in skip:
        R["self_intersection"] = {}
        for n in car.built:
            d = car.nodes[n]
            try:
                R["self_intersection"][n] = self_intersections(d["V"], d["F"])
            except MemoryError as e:
                R["self_intersection"][n] = {"error": str(e)}
    if "clearance" not in skip:
        R["clearance"] = check_clearance(car)
    if "symmetry" not in skip:
        R["symmetry"] = check_symmetry(car)
    if "fascia" not in skip:
        v0car = Car(v0path) if v0path else None
        R["hidden_fascia"] = check_hidden_fascia(car, v0=v0car)
        if v0path:
            R["v0_residue"] = v0_residue(car, v0car)
            R["origin_audit"] = origin_audit(car, v0car)
    R["seconds"] = round(time.time() - t0, 1)
    return R


def jdefault(o):
    """numpy scalars are not JSON-serialisable; never let a report die on that."""
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("car")
    m.add_argument("--v0", default=None)
    m.add_argument("--label", default=None)
    m.add_argument("--out", required=True)
    m.add_argument("--skip", default="")
    s = sub.add_parser("selftest")
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "measure":
        R = measure(a.car, a.v0, a.label, skip=set(x for x in a.skip.split(",") if x))
        json.dump(R, open(a.out, "w"), indent=1, default=jdefault)
        print(json.dumps({k: R[k] for k in ("label", "sha256", "bbox_m", "seconds")}, indent=1, default=jdefault))
        if "hierarchy" in R:
            h = R["hierarchy"]
            print(f"hierarchy: present={len(h['present'])}/{len(REQUIRED)} "
                  f"missing={h['missing']} empty={h['empty']} shared={h['shared_mesh']}")
        if "hidden_fascia" in R:
            f = R["hidden_fascia"]
            print(f"fascia: component-first rays {f['rays_component_first']}, "
                  f"with shell behind {f['rays_component_first_with_shell_behind']} "
                  f"({f['nested_pct_of_component_rays']}%)")
        if "v0_residue" in R:
            print(f"v0 front-zone faces retained: {R['v0_residue']['retained_pct_total']}%")
        print("MEASURE_DONE")
    else:
        from selftest import run_selftest
        R = run_selftest()
        json.dump(R, open(a.out, "w"), indent=1, default=jdefault)
        bad = [k for k, v in R.items() if isinstance(v, dict) and v.get("control_ok") is False]
        print(json.dumps(R, indent=1, default=jdefault)[:4000])
        print("FAILED CONTROLS:", bad if bad else "none")
        print("SELFTEST_DONE")


if __name__ == "__main__":
    main()
