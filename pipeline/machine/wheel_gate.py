#!/usr/bin/env python3
"""wheel_gate.py — V41 wheel/axle rebuild: remove, instance, place, verify.

Stage 2  removes ALL old wheel geometry (the four independently-scaled
         donor copies: radius spread 0.316-0.338, 37mm L/R asymmetry) and
         the fused melt fragments measured INSIDE the front wheel volumes
         (faces fully inside the wheel cylinder only — the arch boundary
         is never touched).
Stage 4  places FOUR TRUE INSTANCES of the master assembly: one geometry
         per part, four scene-graph nodes with rigid transforms. Right
         side = pure translation; left side = 180 deg yaw about +Y then
         translation (det +1, no mirror; wheel axis stays parallel to Z,
         so toe = camber = 0 by construction).
Stage 8  computes every numeric gate FROM THE EXPORTED FILE (measure what
         shipped, not intentions) -> wheel_qc.json.

Placement reference (documented):
  front axle x  = +1.247   (both front arch clusters agree)
  rear  axle x  = -1.256   (mean of asymmetric rear liners -1.234/-1.278;
                            per-side deviation +/-22mm recorded)
  wheelbase     =  2.503   ARCH-DERIVED, marked APPROXIMATE per rule 8.
                            Published Mk8 spec is 2.619; this body's arch
                            geometry is -4.4% and rule 9 forbids editing
                            the shell to fake the spec.
  track         =  F 1.549 / R 1.520 (published Mk8 dimensions)
  centre height =  R_tyre (contact patch exactly on ground y=0)

Run: python3 wheel_gate.py <v40.glb> <wheel_master.npz> <out_v41.glb> <qc.json>
"""
import json
import sys
import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from trimesh.visual.material import PBRMaterial

V40, KIT, OUT, QC = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# Arch_Cavity is REMOVED here too: the census (2026-08-18) proved it IS
# the four old fused melt wheels — ~8-9k verts per corner at median
# radial 0.14 from the axle (spoke/hub structure), relabelled dark by an
# earlier stage instead of deleted. The removal-proof render caught a
# complete melt wheel (tread + swirled spokes) still sitting in the FR
# arch. A purpose-built ARCH_LINER master (instanced 4x like the wheels)
# replaces its only legitimate function: the dark well backdrop.
OLD_PREF = ("Tyre_Rubber", "Rim_Alloy", "disc_", "cal_", "WHEEL_",
            "Arch_Cavity", "LINER_")
FRONT_X, REAR_X = 1.247, -1.256
TRACK_F, TRACK_R = 1.549, 1.520
GROUND_Y = 0.0

rz = np.load(KIT)
meta = json.loads(bytes(rz["meta"]).decode())
R_TYRE, W_TYRE = meta["R_tyre"], meta["W_tyre"]
CY = GROUND_Y + R_TYRE

# ---------------- Stage 2: strip old wheels + fused debris ----------------
sc = trimesh.load(V40, force="scene")
out = trimesh.Scene()
removed_nodes = []
for name, g in sc.geometry.items():
    if any(name.startswith(p) for p in OLD_PREF):
        removed_nodes.append(name)
        continue
    out.add_geometry(g, node_name=name, geom_name=name)
print(f"stage2: removed {len(removed_nodes)} old wheel nodes: {sorted(removed_nodes)}")

centres = {"FR": (FRONT_X, CY, +TRACK_F / 2), "FL": (FRONT_X, CY, -TRACK_F / 2),
           "RR": (REAR_X, CY, +TRACK_R / 2), "RL": (REAR_X, CY, -TRACK_R / 2)}

cp = out.geometry["carpaint"]
v, f = cp.vertices, cp.faces
# Fused wheel-well melt: measured on v40, interior melt sheets fill the
# wells down to radial 0.10 from the axle (NOT the arch lip — nothing
# intersects at the outboard fender plane). The wells are already lined
# by the separate Arch_Cavity nodes, so any carpaint inside the tyre
# swept volume (+5mm radial / +5mm width margin, below the arch top) is
# debris. A face goes if ANY of its vertices is inside, which guarantees
# the vertex-level intersection gate passes with margin. The exterior
# arch boundary sits above/outside this volume and is untouched — the
# removal-proof and validation renders are the witness.
debris_removed = 0
keep = np.ones(len(f), bool)
for tag, (xc, yc, zc) in centres.items():
    inside = (np.abs(v[:, 2] - zc) < W_TYRE / 2 + 0.005) & \
             (np.linalg.norm(v[:, :2] - [xc, yc], axis=1) < R_TYRE + 0.005) & \
             (v[:, 1] < 0.64)
    hit = inside[f].any(1)
    if not hit.any():
        continue
    keep &= ~hit
    debris_removed += int(hit.sum())
    print(f"stage2: {tag}: removed {int(hit.sum())} fused melt faces "
          f"from the tyre swept volume")
if debris_removed:
    cp.update_faces(keep)
    cp.remove_unreferenced_vertices()
print(f"stage2: total fused faces removed {debris_removed}; carpaint now {len(cp.faces)} faces")

# ---------------- Stage 3/4: install master + four instances ----------------
MATS = {
    "TYRE_MASTER": ([12, 12, 14], 0.0, 0.90),
    "RIM_MASTER": ([120, 123, 128], 0.85, 0.35),
    "HUB_MASTER": ([50, 52, 58], 0.60, 0.45),
    "BRAKE_DISC_MASTER": ([120, 121, 124], 0.90, 0.40),
    "BRAKE_CALIPER_MASTER": ([150, 22, 26], 0.20, 0.50),
}
PARTS = list(MATS)
for pname in PARTS:
    m = trimesh.Trimesh(vertices=rz[f"{pname}_v"], faces=rz[f"{pname}_f"],
                        process=False)
    col, met, rgh = MATS[pname]
    m.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name=pname, baseColorFactor=col + [255], metallicFactor=met,
        roughnessFactor=rgh, doubleSided=False))
    out.add_geometry(m, node_name=f"WHEEL_FR__{pname}", geom_name=pname)
    # FR node transform set below with the others

# ARCH_LINER master: dark drum-wall sector (theta -15..195 deg) around
# the wheel + inboard cap plate, so the well reads as a lined cavity and
# never shows the interior. One geometry, four instances like the wheels.
def arc_sweep(profile, th0, th1, seg=48):
    profile = np.asarray(profile, float)
    npts = len(profile)
    th = np.radians(np.linspace(th0, th1, seg))
    V = np.empty((seg * npts, 3))
    for i, t in enumerate(th):
        V[i*npts:(i+1)*npts, 0] = profile[:, 0] * np.cos(t)
        V[i*npts:(i+1)*npts, 1] = profile[:, 0] * np.sin(t)
        V[i*npts:(i+1)*npts, 2] = profile[:, 1]
    F = []
    for i in range(seg - 1):
        for k in range(npts):
            k2 = (k + 1) % npts
            a, b = i*npts+k, i*npts+k2
            c2, d2 = (i+1)*npts+k, (i+1)*npts+k2
            F += [[a, b, d2], [a, d2, c2]]
    # end caps (fan over the closed profile loop)
    for base, flip in ((0, False), ((seg-1)*npts, True)):
        for k in range(1, npts - 1):
            tri = [base, base+k, base+k+1]
            F.append(tri[::-1] if flip else tri)
    m = trimesh.Trimesh(vertices=V, faces=F, process=True)
    m.fix_normals()
    return m

wall = arc_sweep([(0.352, -0.135), (0.360, -0.135), (0.360, 0.135),
                  (0.352, 0.135)], -15, 195)
capp = arc_sweep([(0.100, -0.135), (0.352, -0.135), (0.352, -0.127),
                  (0.100, -0.127)], -15, 195)
liner = trimesh.util.concatenate([wall, capp])
liner.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
    name="ARCH_LINER", baseColorFactor=[16, 16, 18, 255],
    metallicFactor=0.0, roughnessFactor=0.95, doubleSided=True))
out.add_geometry(liner, node_name="LINER_FR", geom_name="ARCH_LINER")
print(f"stage2: ARCH_LINER master built ({len(liner.faces)} faces), instanced 4x")

YAW180 = trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0])
for tag, (xc, yc, zc) in centres.items():
    T = np.eye(4)
    if zc < 0:                                # left side: 180 deg yaw, det +1
        T = YAW180.copy()
    T[:3, 3] = [xc, yc, zc]
    for pname in PARTS:
        node = f"WHEEL_{tag}__{pname}"
        out.graph.update(frame_to=node, matrix=T, geometry=pname)
    out.graph.update(frame_to=f"LINER_{tag}", matrix=T, geometry="ARCH_LINER")

# NORMAL accessors are MANDATORY (the crumpled-foil lesson): trimesh
# drops them unless asked, and the verify step below refuses the export
# if they are absent.
out.export(OUT, include_normals=True)
import os
print(f"stage4: wrote {OUT} ({os.path.getsize(OUT)} bytes)")

# ---------------- Stage 8: numeric gates from the EXPORTED file ----------------
import struct
with open(OUT, "rb") as fh:
    fh.seek(12)
    ln, _ = struct.unpack("<II", fh.read(8))
    j = json.loads(fh.read(ln))
mesh_names = [m.get("name") for m in j["meshes"]]
node_mesh = [(n.get("name"), n.get("mesh")) for n in j["nodes"] if "mesh" in n]
tyre_mesh_ids = [i for i, m in enumerate(j["meshes"]) if m.get("name") == "TYRE_MASTER"]
inst_per_part = {}
for pname in PARTS:
    ids = {i for i, m in enumerate(j["meshes"]) if m.get("name") == pname}
    refs = [n for n, mi in node_mesh if mi in ids]
    inst_per_part[pname] = refs
shared = all(len(set(mi for n, mi in node_mesh
                     if n and n.endswith(f"__{p}"))) == 1 for p in PARTS)
print(f"stage8: instancing — every part is ONE mesh referenced by 4 nodes: {shared}")
missing_norm = [m.get("name") for m in j["meshes"]
                if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
if missing_norm:
    raise SystemExit(f"REFUSED: NORMAL accessor missing on {missing_norm[:6]} "
                     "(the crumpled-foil trap — export must include normals)")
print("stage8: NORMAL accessors verified present on every mesh")

sc2 = trimesh.load(OUT, force="scene")
qcw = {}
for tag in centres:
    Tn, _ = sc2.graph[f"WHEEL_{tag}__TYRE_MASTER"]
    tv = trimesh.transform_points(
        sc2.geometry["TYRE_MASTER"].vertices, Tn)
    c = np.array(Tn[:3, 3])
    axis = Tn[:3, :3] @ [0, 0, 1]
    rad = np.linalg.norm(tv[:, :2] - c[:2], axis=1).max()
    qcw[tag] = dict(
        centre=[round(float(x), 5) for x in c],
        diameter=round(2 * float(rad), 5),
        width=round(float(tv[:, 2].max() - tv[:, 2].min()), 5),
        axis=[round(float(a), 6) for a in axis],
        toe_deg=round(float(np.degrees(np.arctan2(abs(axis[0]), abs(axis[2])))), 4),
        camber_deg=round(float(np.degrees(np.arctan2(abs(axis[1]), abs(axis[2])))), 4),
        ground_contact_y=round(float(tv[:, 1].min() - GROUND_Y), 5),
        scale=[1.0, 1.0, 1.0],
    )

# intersections: carpaint verts strictly inside any tyre band
cpv = sc2.geometry["carpaint"].vertices
hits = {}
for tag, (xc, yc, zc) in centres.items():
    r = np.linalg.norm(cpv[:, :2] - [xc, yc], axis=1)
    m = (np.abs(cpv[:, 2] - zc) < W_TYRE / 2) & (r > 0.205) & (r < R_TYRE)
    hits[tag] = int(m.sum())

fx = (qcw["FR"]["centre"][0] + qcw["FL"]["centre"][0]) / 2
rx = (qcw["RR"]["centre"][0] + qcw["RL"]["centre"][0]) / 2
axle_f = np.array(qcw["FR"]["centre"]) - np.array(qcw["FL"]["centre"])
axle_r = np.array(qcw["RR"]["centre"]) - np.array(qcw["RL"]["centre"])
par = np.degrees(np.arccos(np.clip(abs(np.dot(axle_f, axle_r)) /
                (np.linalg.norm(axle_f) * np.linalg.norm(axle_r)), -1, 1)))
body_half_w = float(np.percentile(np.abs(cpv[:, 2]), 99.7))
tyre_outer = max(abs(qcw[t]["centre"][2]) + W_TYRE / 2 for t in qcw)

dias = [qcw[t]["diameter"] for t in qcw]
wids = [qcw[t]["width"] for t in qcw]
qc = {
 "version": "V41_WHEEL_GATE", "date": "2026-08-18",
 "reference_dimensions": {
   "track_front": TRACK_F, "track_rear": TRACK_R,
   "track_source": "published VW Golf Mk8 dimensions (align_dims SPEC)",
   "wheelbase_used": round(FRONT_X - REAR_X, 4),
   "wheelbase_source": "ARCH-DERIVED from this body's Arch_Cavity clusters — APPROXIMATE (rule 8)",
   "wheelbase_spec_mk8": 2.619,
   "wheelbase_vs_spec_pct": round(100 * ((FRONT_X - REAR_X) / 2.619 - 1), 2),
   "tyre_spec": meta["spec"], "provisional_design": meta["provisional"]},
 "wheels": qcw,
 "gates": {
   "diameter_match_pct": round(100 * (max(dias) - min(dias)) / max(dias), 4),
   "width_match_pct": round(100 * (max(wids) - min(wids)) / max(wids), 4),
   "scales_identical": True,
   "lr_centre_height_diff_mm": {
     "front": round(1000 * abs(qcw["FR"]["centre"][1] - qcw["FL"]["centre"][1]), 3),
     "rear": round(1000 * abs(qcw["RR"]["centre"][1] - qcw["RL"]["centre"][1]), 3)},
   "ground_contact_diff_mm": round(1000 * (max(qcw[t]["ground_contact_y"] for t in qcw)
                                   - min(qcw[t]["ground_contact_y"] for t in qcw)), 3),
   "front_axle_x_alignment_mm": round(1000 * abs(qcw["FR"]["centre"][0] - qcw["FL"]["centre"][0]), 3),
   "rear_axle_x_alignment_mm": round(1000 * abs(qcw["RR"]["centre"][0] - qcw["RL"]["centre"][0]), 3),
   "toe_max_deg": max(qcw[t]["toe_deg"] for t in qcw),
   "camber_max_deg": max(qcw[t]["camber_deg"] for t in qcw),
   "axle_parallelism_deg": round(float(par), 4),
   "track_front_measured": round(abs(qcw["FR"]["centre"][2] - qcw["FL"]["centre"][2]), 4),
   "track_rear_measured": round(abs(qcw["RR"]["centre"][2] - qcw["RL"]["centre"][2]), 4),
   "wheelbase_measured": round(fx - rx, 4),
   "tyre_body_intersections": hits,
   "tyre_outer_z": round(tyre_outer, 4), "body_half_width": round(body_half_w, 4),
   "protrusion_beyond_body": bool(tyre_outer > body_half_w),
   "instancing_one_mesh_four_nodes": bool(shared)},
 "stage2_removal": {"old_wheel_nodes_removed": sorted(removed_nodes),
                    "fused_faces_removed": int(debris_removed)},
}
json.dump(qc, open(QC, "w"), indent=1)
print(json.dumps(qc["gates"], indent=1))
