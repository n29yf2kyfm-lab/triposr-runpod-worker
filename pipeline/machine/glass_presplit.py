#!/usr/bin/env python3
"""glass_presplit.py — split a LABEL-DERIVED glass blob into pane components.

WHY: glass_stage separates and rebuilds named panes, but it refuses a glass
node that is ONE connected component ("it separates, it does not segment").
Label-transfer glass (hybrid_transfer / seg pipelines) is exactly that: one
welded band around the greenhouse, bridged across the pillars wherever the
label bled. Measured on the Yaris hybrid: 131k faces, one mega-component,
classified [roof 0.44, rear_screen 0.24] -> honest refusal.

This stage is the missing step between a labelled blob and glass_stage:

  * classify each glass FACE by its normal + position:
      side L/R    |n_z| >= 0.55
      screen      |n_x| >= 0.30 (front and rear split by position)
      roof-curl   n_y >= 0.55 with |n_x| < 0.25  -> evicted to BODY
                  (the recorded trap: a raked windscreen centre is also
                  up-facing, but it carries |n_x| — the curl does not)
  * evict side glass below a STRAIGHT beltline, robust-fitted per side to
    the upper envelope of the window band's lower edge (the label sag is
    always DOWNWARD, so an iterative fit that drops low outliers converges
    on the true DLO bottom; the recorded stencil-floor lesson: a
    self-calibrated floor that follows the sag is no floor at all)
  * emit the panes as DISCONNECTED components in one 'glass' geometry
    (per-class submesh + concatenate duplicates the border vertices, which
    is what breaks the weld), evicted faces are appended to the body node.

Everything measured lands in <out>_presplit_qc.json. The stage REFUSES when
the split finds fewer than 2 substantial panes — a car whose glass cannot
be split here needs synthesis, not silent passing.

Run: python3 glass_presplit.py <in.glb> <out.glb> [--spec specs/car.json]
"""
import json
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
SPEC = None
for i, a in enumerate(sys.argv):
    if a == "--spec":
        SPEC = sys.argv[i + 1]
spec = CarSpec.empty() if SPEC is None else CarSpec.load(SPEC)
QC = {"stage": "glass_presplit", "input": INP, "spec": spec.path, "derived": {}}

glass_label = spec.label("glass", "glass")
body_label = spec.label("body", "carpaint")

sc = trimesh.load(INP, force="scene")
if glass_label not in sc.geometry:
    raise SystemExit(f"REFUSED: no {glass_label!r} geometry in {INP}")
g = sc.geometry[glass_label]
body = sc.geometry[body_label]

n = g.face_normals
c = g.triangles_center
allv = np.vstack([body.vertices, g.vertices])
gx0, gx1 = float(allv[:, 0].min()), float(allv[:, 0].max())
gy = float(allv[:, 1].min())
H = float(np.percentile(allv[:, 1], 99.8)) - gy
L = gx1 - gx0
xf = (c[:, 0] - gx0) / L
yf = (c[:, 1] - gy) / H

cls = np.full(len(g.faces), "amb", dtype=object)
curl = (np.abs(n[:, 1]) >= 0.55) & (np.abs(n[:, 0]) < 0.25)
side = ~curl & (np.abs(n[:, 2]) >= 0.55)
screen = ~curl & ~side & (np.abs(n[:, 0]) >= 0.30)
cls[curl] = "curl"
cls[side & (c[:, 2] >= 0)] = "side_R"
cls[side & (c[:, 2] < 0)] = "side_L"
cls[screen & (xf >= 0.5)] = "screen_F"
cls[screen & (xf < 0.5)] = "screen_R"
# ambiguous faces (pillar bleed, diagonal normals): give them to the
# nearest substantial class centroid so they cannot bridge two panes
amb = cls == "amb"
if amb.any():
    cents = {}
    for k in ("side_R", "side_L", "screen_F", "screen_R"):
        m = cls == k
        if m.sum() > 50:
            cents[k] = c[m].mean(0)
    if cents:
        keys = list(cents)
        D = np.stack([np.linalg.norm(c[amb] - cents[k], axis=1) for k in keys])
        cls[np.where(amb)[0]] = np.array(keys, dtype=object)[D.argmin(0)]
    else:
        cls[amb] = "curl"          # nothing to attach to: evict

# ---- straight-beltline eviction per side --------------------------------
def beltline_fit(mask, tag):
    """Robust straight-line fit to the UPPER envelope of the side band's
    lower edge. Sag is always downward: iteratively drop bins far BELOW
    the line and refit; what remains is the true DLO bottom."""
    xs, ys = c[mask, 0], c[mask, 1]
    nb = 40
    edges = np.linspace(xs.min(), xs.max(), nb + 1)
    bx, by = [], []
    idx = np.clip(np.searchsorted(edges, xs) - 1, 0, nb - 1)
    for b in range(nb):
        sel = idx == b
        if sel.sum() >= 3:
            bx.append((edges[b] + edges[b + 1]) / 2)
            by.append(ys[sel].min())
    bx, by = np.array(bx), np.array(by)
    if len(bx) < 8:
        return None
    keep = np.ones(len(bx), bool)
    for _ in range(4):
        A = np.stack([np.ones(keep.sum()), bx[keep]], 1)
        coef, *_ = np.linalg.lstsq(A, by[keep], rcond=None)
        r = by - (coef[0] + coef[1] * bx)
        mad = max(float(np.median(np.abs(r[keep] - np.median(r[keep])))), 0.004)
        nk = ~(r < -2.0 * mad)
        if (nk == keep).all():
            break
        keep = nk
    QC["derived"][f"beltline_{tag}"] = {
        "a": round(float(coef[0]), 4), "b_per_m": round(float(coef[1]), 5),
        "bins_used": int(keep.sum()), "bins_dropped_sag": int((~keep).sum())}
    return coef

evicted_belt = 0
for tag in ("side_R", "side_L"):
    m = cls == tag
    if m.sum() < 200:
        continue
    coef = beltline_fit(m, tag)
    if coef is None:
        continue
    below = m & (c[:, 1] < coef[0] + coef[1] * c[:, 0] - 0.005)
    cls[below] = "curl"            # evicted with the curl class -> body
    evicted_belt += int(below.sum())

# screens: glazing lives high — glass in a screen class below 0.45 of body
# height is bumper/cowl label noise (the recorded ends rule)
low_scr = np.isin(cls, ["screen_F", "screen_R"]) & (yf < 0.45)
cls[low_scr] = "curl"

# ---- reassemble ----------------------------------------------------------
panes = []
table = {}
for k in ("screen_F", "screen_R", "side_R", "side_L"):
    m = cls == k
    table[k] = int(m.sum())
    if m.sum() >= 150:
        panes.append(g.submesh([np.where(m)[0]], append=True))
evict = np.isin(cls, ["curl"])
table["evicted_to_body"] = int(evict.sum())
table["evicted_beltline"] = evicted_belt
QC["derived"]["face_table"] = table
print("presplit:", json.dumps(table))
if len(panes) < 2:
    QC["status"] = "REFUSED"
    QC["reason"] = f"only {len(panes)} substantial panes after split: {table}"
    json.dump(QC, open(OUT.replace(".glb", "_presplit_qc.json"), "w"), indent=1)
    raise SystemExit(f"REFUSED: {QC['reason']}")

def _fresh_visual(src):
    """A NEW TextureVisuals holding the source's material. Reassigning the
    ORIGINAL visuals object onto a mesh with a different vertex count left
    a stale-length uv array behind — the export then dropped the material
    binding and the evicted roof faces rendered default-white and took no
    paint (measured on the Yaris premium red control)."""
    mat = getattr(src.visual, "material", None)
    return trimesh.visual.TextureVisuals(material=mat)


new_glass = trimesh.util.concatenate(panes)
new_glass.visual = _fresh_visual(g)
if evict.any():
    ev = g.submesh([np.where(evict)[0]], append=True)
    ev.visual = _fresh_visual(body)
    new_body = trimesh.util.concatenate([body, ev])
    new_body.visual = _fresh_visual(body)
else:
    new_body = body

out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn == glass_label:
        out.add_geometry(new_glass, geom_name=gn, node_name=node, transform=T)
    elif gn == body_label:
        out.add_geometry(new_body, geom_name=gn, node_name=node, transform=T)
    elif gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                         transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
out.export(OUT, include_normals=True)
QC["status"] = "OK"
comps_after = len(trimesh.load(OUT, force="scene")
                  .geometry[glass_label].split(only_watertight=False))
QC["derived"]["glass_components_after"] = comps_after
print(f"glass components after split: {comps_after}")
json.dump(QC, open(OUT.replace(".glb", "_presplit_qc.json"), "w"), indent=1)
print(f"wrote {OUT}")
