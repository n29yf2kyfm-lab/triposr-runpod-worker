#!/usr/bin/env python3
"""survey.py -- GATE 3 v7 step 0: measure the base file. Reads only.

Everything the builder needs about the frame is DERIVED here and written to
survey.json, so no downstream stage assumes a frame.  Three things this exists
to establish, each of which a predecessor got wrong by assuming:

  * WHICH END IS THE NOSE.  `canon_dims.py`'s nose rule gets this family of
    files wrong and does not warn, and `front_kit.py` builds at XMAX which on
    a nose-at-XMIN car puts the whole kit on the tailgate.  Here the nose is
    decided by the LAMP NODES' own centroid (Headlamp_L/R vs TailLamp_L/R),
    which is a semantic fact carried by the file, and then cross-checked
    against the wheel centres.  A render still confirms it before any build.

  * WHERE THE GROUND IS.  This car is NOT grounded: the tyre contact points
    sit well below y=0, and it has rake.  Gate 6's lesson is that a car's
    ground plane is its CONTACT PATCHES, never the lowest vertex in the scene
    (which is underbody).  Ground is taken as the mean of the four tyre
    minima, and the rake is reported rather than removed -- regrounding is
    Gate 6's scope, not this gate's.

  * WHAT THE NOSE PLANE IS.  Taken from the frontmost real bodywork, not the
    scene bbox, because mirrors and arch liners can overhang.

Run: python3 survey.py <car.glb> <out.json>
"""
import json
import sys

import numpy as np
import trimesh

CAR, OUT = sys.argv[1], sys.argv[2]

sc = trimesh.load(CAR, force="scene", process=False)

rows = []
world = {}
for node in sc.graph.nodes_geometry:
    T, gname = sc.graph[node]
    g = sc.geometry[gname]
    v = trimesh.transform_points(np.asarray(g.vertices, float), T)
    world[node] = v
    rows.append({
        "node": node, "geometry": gname,
        "faces": int(len(g.faces)), "verts": int(len(g.vertices)),
        "min": [round(float(x), 5) for x in v.min(0)],
        "max": [round(float(x), 5) for x in v.max(0)],
        "material": (getattr(getattr(g.visual, "material", None), "name", None) or ""),
    })
rows.sort(key=lambda r: -r["faces"])

allv = np.vstack(list(world.values()))
bmin, bmax = allv.min(0), allv.max(0)
ext = bmax - bmin

# ---------------------------------------------------------------- nose sense
lampf = [n for n in world if n.startswith("Headlamp_")]
lampr = [n for n in world if n.startswith("TailLamp_")]
if not lampf or not lampr:
    raise SystemExit("survey: no Headlamp_*/TailLamp_* nodes -- nose undecidable")
fx = float(np.mean([world[n][:, 0].mean() for n in lampf]))
rx = float(np.mean([world[n][:, 0].mean() for n in lampr]))
nose_at = "XMIN" if fx < rx else "XMAX"

# cross-check: front wheels should be on the same side as the headlamps
wf = [n for n in world if n.startswith(("Wheel_FL", "Wheel_FR"))]
wr = [n for n in world if n.startswith(("Wheel_RL", "Wheel_RR"))]
wfx = float(np.mean([world[n][:, 0].mean() for n in wf])) if wf else float("nan")
wrx = float(np.mean([world[n][:, 0].mean() for n in wr])) if wr else float("nan")
wheel_agrees = bool((wfx < wrx) == (fx < rx))

# ------------------------------------------------------------- ground / rake
tyres = {}
for n in world:
    if n.startswith("Wheel_") and n.endswith("_Tyre"):
        tyres[n] = float(world[n][:, 1].min())
GY = float(np.mean(list(tyres.values()))) if tyres else float("nan")
front_t = [v for k, v in tyres.items() if k.startswith(("Wheel_FL", "Wheel_FR"))]
rear_t = [v for k, v in tyres.items() if k.startswith(("Wheel_RL", "Wheel_RR"))]
rake_mm = (np.mean(rear_t) - np.mean(front_t)) * 1000 if front_t and rear_t else float("nan")
scene_low = float(bmin[1])

# --------------------------------------------------------------- nose plane
# frontmost bodywork, ignoring the 0.05% most extreme points (stray verts)
sgn = 1.0 if nose_at == "XMIN" else -1.0
xs = allv[:, 0] * sgn
XNOSE = float(np.percentile(xs, 0.05) * sgn)
XNOSE_abs = float(bmin[0] if nose_at == "XMIN" else bmax[0])

# lateral centre from the plate-bearing bodywork is not available yet; use the
# body shell's own z symmetry as a first estimate and report it, do not use it
# as a datum without checking.
bs = world.get("Body_Shell")
zc_body = float(0.5 * (bs[:, 2].min() + bs[:, 2].max())) if bs is not None else float("nan")

out = {
    "file": CAR,
    "nodes": len(rows), "faces_total": int(sum(r["faces"] for r in rows)),
    "bbox_min": [round(float(x), 5) for x in bmin],
    "bbox_max": [round(float(x), 5) for x in bmax],
    "extent": [round(float(x), 5) for x in ext],
    "nose_at": nose_at,
    "nose_evidence": {
        "headlamp_mean_x": round(fx, 5), "taillamp_mean_x": round(rx, 5),
        "front_wheel_mean_x": round(wfx, 5), "rear_wheel_mean_x": round(wrx, 5),
        "wheels_agree_with_lamps": wheel_agrees,
        "note": "SEMANTIC + wheel cross-check only. Must be confirmed by render "
                "before any geometry is built.",
    },
    "ground": {
        "tyre_minima": {k: round(v, 5) for k, v in sorted(tyres.items())},
        "GY_contact_plane": round(GY, 5),
        "rake_mm_rear_minus_front": round(float(rake_mm), 2),
        "scene_lowest_y": round(scene_low, 5),
        "scene_low_minus_GY_mm": round((scene_low - GY) * 1000, 2),
        "note": "GY is the mean of the four TYRE minima (Gate 6 rule: a car's "
                "ground plane is its contact patches). The scene's lowest vertex "
                "is NOT the ground.",
    },
    "nose_plane": {"x_p005": round(XNOSE, 5), "x_bbox": round(XNOSE_abs, 5)},
    "body_shell_z_centre": round(zc_body, 5),
    "geometries": rows,
}
json.dump(out, open(OUT, "w"), indent=1)

print(f"nodes {out['nodes']}  faces {out['faces_total']}")
print(f"extent x {ext[0]:.4f} y {ext[1]:.4f} z {ext[2]:.4f}")
print(f"NOSE AT {nose_at}  (headlamp x {fx:+.4f} vs taillamp x {rx:+.4f}; "
      f"wheels agree={wheel_agrees})")
print(f"GROUND GY {GY:+.5f}  rake {rake_mm:+.1f}mm (rear-front)  "
      f"scene low {scene_low:+.5f} = GY{(scene_low-GY)*1000:+.1f}mm")
print(f"nose plane x {XNOSE:+.5f} (bbox {XNOSE_abs:+.5f})")
print("top nodes by faces:")
for r in rows[:8]:
    print(f"  {r['node']:22s} {r['faces']:7d}f  x {r['min'][0]:+.3f}..{r['max'][0]:+.3f}"
          f"  y {r['min'][1]:+.3f}..{r['max'][1]:+.3f}  z {r['min'][2]:+.3f}..{r['max'][2]:+.3f}")
