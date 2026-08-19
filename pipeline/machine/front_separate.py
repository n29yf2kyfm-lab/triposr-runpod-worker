#!/usr/bin/env python3
"""front_separate.py — Stage 5: the front becomes separate NAMED assemblies.

Mirror of rear_separate (Stage 4), built car-agnostic from the start:
every threshold derives from the body's own measured frame or from
upstream stage contracts, never from absolute coordinates.

  * Bonnet       — front-zone faces that FACE UP, inside the wing line
  * Front_Bumper — the low forward cap beyond the front axle
  * Front_Wing_L / Front_Wing_R — side-facing front-zone panels
  * everything else in the front zone stays body shell (the fascia the
    grille/lamp kit sits over)

Anchors, in order of evidence:
  cowl line   = Glass_Windscreen pane min-x (stage-2 contract) — else
                nose - 0.45 x L, APPROXIMATE, recorded
  front axle  = WHEEL_FR__TYRE_MASTER node translation (stage-1
                contract) — else the label-free arch detector — else
                nose - 0.20 x L, APPROXIMATE, recorded

DIAGNOSTIC-FIRST GATE (council rule): run --tag first. It recolours the
selection (bonnet MAGENTA, bumper YELLOW, wing L CYAN, wing R ORANGE per
the brief's diagnostic-colour convention), deletes nothing, and the
locked-rig render of that file is the go/no-go before any cut.

One physical paint everywhere: the split parts copy the body paint's
material values exactly (stage-3 rule) — separate NODES, same paint.

Run: python3 front_separate.py <in.glb> <out.glb> [--spec spec.json] [--tag]
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
TAG_ONLY = "--tag" in sys.argv
SPEC = None
for i, a in enumerate(sys.argv):
    if a == "--spec":
        SPEC = sys.argv[i + 1]
spec = CarSpec.load(SPEC) if SPEC else CarSpec.empty()

QC = {"stage": "front_separate", "input": INP, "spec": spec.path,
      "derived": {}, "self_tests": {}, "decisions": {}}

# thresholds — fractions of the measured frame, calibration noted
BUMPER_H_FRAC = 0.33     # same fraction the validated rear stage uses
BUMPER_X_FRAC = 0.50     # bumper zone starts halfway from axle to nose
BONNET_NY = 0.45         # a bonnet face points up
BONNET_Z_FRAC = 0.72     # wing line: bonnet occupies the central 72% of
                         # half-width (Golf bonnet ~1.3m of 1.79m body)
WING_NZ = 0.50           # a wing face points sideways

sc = trimesh.load(INP, force="scene")
body_label = spec.label("body", "carpaint")
if body_label not in sc.geometry:
    QC["status"] = "REFUSED"
    QC["reason"] = f"body node {body_label!r} absent; scene: {sorted(sc.geometry)[:20]}"
    json.dump(QC, open(OUT.replace(".glb", "_front_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")
cp = sc.geometry[body_label]
v = cp.vertices
x0, x1 = float(v[:, 0].min()), float(v[:, 0].max())
L = x1 - x0
H0 = float(v[:, 1].min())
H = float(np.percentile(v[:, 1], 99.8)) - H0
HW = float(np.percentile(np.abs(v[:, 2]), 99.7))

# ---- cowl line
cowl_x, cowl_src = None, None
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn == "Glass_Windscreen":
        gv = trimesh.transform_points(sc.geometry[gn].vertices, T)
        cowl_x = float(gv[:, 0].min())
        cowl_src = "Glass_Windscreen pane min-x (stage-2 contract)"
        break
if cowl_x is None:
    cowl_x = x1 - 0.45 * L
    cowl_src = "APPROXIMATE fallback nose - 0.45 x L (no windscreen pane)"
QC["derived"]["cowl_x"] = {"value": round(cowl_x, 4), "source": cowl_src}

# ---- front axle
fx, fx_src = None, None
if "WHEEL_FR__TYRE_MASTER" in sc.graph.nodes_geometry:
    # from transformed VERTICES, not the node translation: downstream
    # stages bake instance transforms (measured: T.x read 0.000 on run3's
    # baked chain, bumper got 0 faces) — the vertex cloud is true either way
    _T, _gn = sc.graph["WHEEL_FR__TYRE_MASTER"]
    _tv = trimesh.transform_points(sc.geometry[_gn].vertices, _T)
    fx = float((_tv[:, 0].min() + _tv[:, 0].max()) / 2)
    fx_src = "WHEEL_FR tyre vertex-cloud centre (bake-proof)"
else:
    try:
        from wheel_stage import detect_arches
        det = detect_arches(v, {}, strict=False)
        if det:
            fx = det["front_x"]
            fx_src = "label-free arch detector (no wheel nodes present)"
    except Exception:
        pass
if fx is None:
    fx = x1 - 0.20 * L
    fx_src = "APPROXIMATE fallback nose - 0.20 x L"
QC["derived"]["front_axle_x"] = {"value": round(fx, 4), "source": fx_src}
print(f"frame: nose {x1:.3f}, cowl {cowl_x:.3f} ({cowl_src.split('(')[0].strip()}), "
      f"axle {fx:.3f}, H {H:.3f}, HW {HW:.3f}")

cent = cp.triangles_center
fn = cp.face_normals
front = cent[:, 0] > cowl_x
bumper = front & (cent[:, 0] > fx + BUMPER_X_FRAC * (x1 - fx)) & \
         (cent[:, 1] < H0 + BUMPER_H_FRAC * H)
# BONNET BY RASTERISED TOP SURFACE, not by normals: 46% of this body
# class's front faces carry FLIPPED normals (measured here: 5,074 up vs
# 5,325 down on the bonnet top — the recorded "never orient off
# generated-body normals" lesson, which the --tag render caught before
# any cut). A face is bonnet if it sits within 2.5% of body height of
# the front zone's TOP surface at its own (x,z) cell.
CELL = 0.04
# ceiling: the bonnet ends at the windscreen base — without it the top-
# surface raster climbs the A-pillars and header (seen in tag render 2)
wsy = None
for _n in sc.graph.nodes_geometry:
    _T, _gn = sc.graph[_n]
    if _gn == "Glass_Windscreen":
        wsy = float(trimesh.transform_points(
            sc.geometry[_gn].vertices, _T)[:, 1].min())
        break
y_ceil = (wsy + 0.02 * H) if wsy is not None else (H0 + 0.62 * H)
QC["derived"]["bonnet_y_ceiling"] = {
    "value": round(float(y_ceil), 4),
    "source": ("windscreen pane base + 2%H" if wsy is not None
               else "APPROXIMATE fallback 62% of body height")}
zone = front & ~bumper & (np.abs(cent[:, 2]) < BONNET_Z_FRAC * HW) & \
       (cent[:, 1] < y_ceil)
zi = np.where(zone)[0]
cx = np.floor(cent[zi, 0] / CELL).astype(int)
cz = np.floor(cent[zi, 2] / CELL).astype(int)
key = (cx - cx.min()) * 1000 + (cz - cz.min())
maxy = {}
for k, y in zip(key, cent[zi, 1]):
    if y > maxy.get(k, -9e9):
        maxy[k] = y
topface = np.array([cent[i, 1] >= maxy[k] - 0.025 * H for i, k in zip(zi, key)])
bonnet = np.zeros(len(cent), bool)
bonnet[zi[topface]] = True
# wings live around the front arch, FORWARD of the door line — the cowl
# line sits mid-door at flank height, so the front-zone test alone
# reached the doors (measured in the first --tag render). Door-line
# anchor: midway cowl->axle, APPROXIMATE, render-verified.
door_x = (cowl_x + fx) / 2
wingish = front & ~bumper & ~bonnet & (np.abs(fn[:, 2]) > WING_NZ) & \
          (cent[:, 1] > H0 + BUMPER_H_FRAC * H) & (cent[:, 0] > door_x)
wing_L = wingish & (cent[:, 2] < 0)
wing_R = wingish & (cent[:, 2] > 0)
rest = front & ~bumper & ~bonnet & ~wingish
QC["derived"]["door_line_x"] = {"value": round(float(door_x), 4),
                                "source": "APPROXIMATE midway cowl->front axle"}
print(f"front zone {front.sum()} faces: bonnet {bonnet.sum()}, "
      f"bumper {bumper.sum()}, wing_L {wing_L.sum()}, wing_R {wing_R.sum()}, "
      f"fascia/shell keeps {rest.sum()}")
QC["decisions"]["face_counts"] = {
    "front_zone": int(front.sum()), "bonnet": int(bonnet.sum()),
    "bumper": int(bumper.sum()), "wing_L": int(wing_L.sum()),
    "wing_R": int(wing_R.sum()), "shell_keeps": int(rest.sum())}

if hasattr(cp.visual, "material"):
    paint_mat = cp.visual.material
else:
    # raw generator bodies carry ColorVisuals, no PBR material — the
    # parts get a recorded neutral so the split can still be judged
    paint_mat = PBRMaterial(name="body_neutral",
                            baseColorFactor=[150, 150, 155, 255],
                            metallicFactor=0.0, roughnessFactor=0.6)
    QC["decisions"]["paint"] = "body had no PBR material (ColorVisuals) — neutral grey recorded"


def submesh(mask, name, colour=None):
    m = cp.copy()
    m.update_faces(mask)
    tri = m.triangles
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    if (area < 1e-10).any():
        m.update_faces(area >= 1e-10)
    m.remove_unreferenced_vertices()
    vn = np.array(m.vertex_normals)
    bad = np.linalg.norm(vn, axis=1) < 1e-6
    if bad.any():
        vn[bad] = [0.0, 1.0, 0.0]
        m.vertex_normals = vn
    if colour is not None:
        mat = PBRMaterial(name=name, baseColorFactor=colour,
                          metallicFactor=0.0, roughnessFactor=0.5)
    else:
        mat = PBRMaterial(name=name,
                          baseColorFactor=list(paint_mat.baseColorFactor),
                          metallicFactor=float(paint_mat.metallicFactor),
                          roughnessFactor=float(paint_mat.roughnessFactor))
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    return m


if TAG_ONLY:
    # diagnostic colours per the production brief's convention
    parts = [(bonnet, "TAG_Bonnet", [255, 0, 220, 255]),
             (bumper, "TAG_Front_Bumper", [255, 220, 0, 255]),
             (wing_L, "TAG_Wing_L", [0, 220, 255, 255]),
             (wing_R, "TAG_Wing_R", [255, 140, 0, 255])]
    out = trimesh.Scene()
    keep = ~ (bonnet | bumper | wing_L | wing_R)
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        g = submesh(keep, body_label) if gn == body_label else sc.geometry[gn]
        if gn not in out.geometry:
            out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    for mask, name, col in parts:
        if mask.any():
            out.add_geometry(submesh(mask, name, col), geom_name=name, node_name=name)
    out.export(OUT, include_normals=True)
    print(f"TAG MODE: wrote {OUT} — render it and LOOK before cutting")
    raise SystemExit(0)

n_before = int(len(cp.faces))
parts = {"Bonnet": bonnet, "Front_Bumper": bumper,
         "Front_Wing_L": wing_L, "Front_Wing_R": wing_R}
built = {k: submesh(m, k) for k, m in parts.items() if m.sum() > 0}
shell = submesh(~(bonnet | bumper | wing_L | wing_R), body_label)

out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn == body_label:
        continue
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
out.add_geometry(shell, geom_name=body_label, node_name=body_label)
for name, m in built.items():
    out.add_geometry(m, geom_name=name, node_name=name)
    print(f"  {name}: {len(m.faces)} faces")

out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
names = [m2.get("name") for m2 in j["meshes"]]
absent = [n for n in built if n not in names]
if absent:
    raise SystemExit(f"REFUSED: nodes missing from export: {absent}")

# ---- self-tests
n_after = int(len(shell.faces)) + sum(len(m.faces) for m in built.values())
acct_ok = abs(n_before - n_after) <= 0.001 * n_before   # sanitation may drop degenerates
QC["self_tests"]["face_accounting"] = {
    "before": n_before, "after_sum": n_after, "pass": bool(acct_ok)}
bn = built.get("Bonnet")
if bn is not None:
    # |ny|, not ny: this body class carries ~50% flipped normals (5,074
    # up vs 5,325 down measured on the bonnet top), so signed mean is
    # meaningless — HORIZONTALITY is the property a bonnet must have
    ny = float((np.abs(bn.face_normals[:, 1]) * bn.area_faces).sum()
               / bn.area_faces.sum())
    QC["self_tests"]["bonnet_horizontal"] = {
        "area_weighted_abs_ny": round(ny, 3), "limit": 0.5,
        "pass": bool(ny > 0.5)}
share = {k: round(float(m.area / cp.area), 4) for k, m in built.items()}
QC["self_tests"]["part_area_share"] = share
failures = [k for k, t in QC["self_tests"].items()
            if isinstance(t, dict) and t.get("pass") is False]
QC["status"] = "FAIL" if failures else "PASS"
json.dump(QC, open(OUT.replace(".glb", "_front_qc.json"), "w"), indent=1)
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes), status {QC['status']}")
if failures:
    raise SystemExit(f"self-tests FAILED: {failures}")
