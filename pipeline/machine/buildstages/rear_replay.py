#!/usr/bin/env python3
"""rear_replay.py — replay REAR GATE v2's operations onto the rebound lineage.

Rear v2 was built on Gate 4's `rear_v3.glb`.  This does NOT transplant its
output; it re-runs `fit_panels -> build_rear -> strip_assemble` against the car
coming out of the merge pipeline, so the result carries ONE material table
(Gate 7+8's, extensions intact) instead of two.

THE MEASUREMENT THAT MADE THE REPLAY POSSIBLE.  `rear_v3.glb` and
`car_rebound.glb` are the same car in the same world frame: identical bbox
minimum (-2.142195, 0.000316, -0.894503), identical height, and a tail profile
(99.7th-percentile x per 50 mm height band at |z| < 0.30) agreeing to under
2 mm at every height from y 0.225 to y 1.375 — the two exceptions being
+16.8 mm at y 0.375 and +4.4 mm at y 0.875, which are Gate 4's own constructed
number plate and lamp solids standing proud of the skin.  So rear v2's
world-space band constants (bumper top 0.560, backlight sill 0.900, patch
domains, the aperture rectangle) needed no re-derivation, and that is a measured
fact rather than an assumption.

WHAT HAD TO CHANGE, and it is only NAMES:
  * outline sources.  `fit_panels` reads each panel's OUTLINE off a separated
    component.  Gate 4 had `Rear_Hatch` and `Rear_Bumper`; this lineage has the
    tailgate inside `Body_Shell`, and its `Bumper_Rear_*` nodes run up to
    y 0.903 — 343 mm past the real bumper shut line.  The bumper outline still
    comes off nodes (`Bumper_Rear_Paint` + `Bumper_Rear_Trim`, which reproduce
    Gate 4's `Rear_Bumper` lateral extent to 0.0-19 mm, mostly under 6 mm); the
    hatch outline is reconstructed geometrically and VALIDATED against Gate 4's
    node — 0.1-15.5 mm through hatch_low, 3-36 mm over most of hatch_surr.
  * the paint and glazing materials are taken from `Body_Shell` and
    `Glass_Rear` instead of Gate 4's `carpaint` / `Rear_Glass` nodes.
  * KEEP.  Gate 4's four constructed tail-lamp solids DO NOT EXIST here — on
    this lineage the best-named rear-lamp nodes (`TailLamp_L/R`) are the
    original melt, which is exactly the "a node whose NAME is right and whose
    GEOMETRY is melt" trap Gate 3 v7 documents.  They are SPARED rather than
    cut, because deleting them would leave the car with no rear lamps at all
    and the production brief forbids removing a component without replacing it.
    Their clearance against the rebuilt skin is MEASURED and reported as a
    residual, not asserted.

WHAT I WOULD HAVE SEEN IF THE REPLAY WERE THE WRONG CALL: the fitted panels
would not have landed on this car — the residual pull would be large rather
than a low-passed correction, the strip footprint would cut geometry the new
panels do not cover, and the hole test would find open rays through the tail.
All three are measured on the output.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MACHINE = os.path.dirname(_HERE)
_R2 = os.path.join(_MACHINE, "rear2")

# node names on the Gate 7+8 rebound lineage
ENV = {
    # points that must not define the measured skin. On this lineage that is the
    # constructed FRONT kit (Gate 3 v7 has already run), the wheels, the mirrors
    # and the melt tail lamps -- lamps sit proud and would make the profile ride
    # the lens crest, which is the reason Gate 4 excluded its own lamp solids.
    # NOTE, and it is the difference between the two lineages: Gate 4 excluded
    # its own lamp SOLIDS because they are constructed parts sitting ON the
    # surface, so including them made the measured profile ride the lens crest.
    # `TailLamp_L/R` on this lineage are not solids, they ARE the skin in the
    # lamp band.  Excluding them made the fit interpolate ACROSS that band and
    # the rebuilt panel then cut through the lamps -- measured, 37-38% of lamp
    # vertices behind the new skin, and visible as dark bands in the az090
    # render.  They stay IN the measured set for that reason.
    "REAR2_EXCLUDE": ",".join([
        "Tail_Lens", "Tail_Housing", "Rear_Plate",
        "Wheel_", "Mirror_", "Headlamp_",
        "Grille", "Bumper_Front", "Lamp_", "DRL", "Plate_", "Intake_",
        "Badge", "TowEye", "Splitter", "Valance_Front", "Chrome_",
    ]),
    "REAR2_SRC_BUMPER": "Bumper_Rear_Paint,Bumper_Rear_Trim",
    "REAR2_SRC_HATCH": "__zone__",
    "REAR2_ZONE_XMIN": "1.35",
    # spared whole: front kit, wheels, glazing, cabin -- and the melt tail lamps,
    # see the docstring.
    "REAR2_KEEP": ",".join([
        "Wheel_", "TailLamp_", "Headlamp_", "Mirror_",
        "Glass_", "Cabin_",
        "Grille", "DRL", "Intake_", "Badge", "TowEye", "Plate_Carrier",
        "Plate", "Splitter", "Valance", "Lamp_", "Chrome_", "Bumper_Front",
    ]),
    "REAR2_DROP": "",
    "REAR2_PAINT_NODE": "Body_Shell",
    "REAR2_GLASS_NODE": "Glass_Rear",
    "REAR2_RENAME": json.dumps({}),
}


def _run(cmd, cwd, log, env=None, check=True):
    e = dict(os.environ)
    e.update(ENV)
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True,
                       timeout=7200)
    out = r.stdout + r.stderr
    with open(log, "a") as fh:
        fh.write(f"\n$ {' '.join(str(c) for c in cmd)}\n(cwd={cwd})\n{out}\n"
                 f"[rc={r.returncode}]\n")
    if check and r.returncode != 0:
        raise SystemExit(f"REAR REPLAY FAILED rc={r.returncode}: {cmd}\n{out[-4000:]}")
    return out


def measure_lamp_clearance(before, after, work):
    """How far the SPARED melt tail lamps sit from the rebuilt skin.

    rear v2 made exactly this measurement for Gate 4's four constructed lamp
    units (0.00% of vertices buried, min clearance +4.65 / +1.86 mm).  The same
    number is reported here for the melt lamps this lineage carries instead, so
    the difference between the two lineages is visible rather than glossed.
    """
    import trimesh
    from scipy.spatial import cKDTree
    sc = trimesh.load(after, force="scene", process=False)

    def W(n):
        T, g = sc.graph[n]
        return trimesh.transform_points(np.asarray(sc.geometry[g].vertices, float), T)

    panels = [n for n in sc.graph.nodes_geometry
              if n in ("Hatch", "Bumper_Rear", "Hatch_Inner", "Bumper_Rear_Inner")]
    if not panels:
        return {"note": "no rebuilt panels found"}
    PV = np.vstack([W(n) for n in panels])
    tree = cKDTree(PV)
    out = {"panels": panels}
    for lam in [n for n in sc.graph.nodes_geometry if n.startswith("TailLamp")]:
        L = W(lam)
        d, i = tree.query(L, k=1, workers=2)
        # signed: outboard (larger x than the nearest panel vertex) = proud
        proud = L[:, 0] - PV[i][:, 0]
        out[lam] = {
            "verts": int(len(L)),
            "buried_pct": round(float(100 * (proud < -0.002).mean()), 3),
            "min_proud_mm": round(float(proud.min() * 1000), 3),
            "median_proud_mm": round(float(np.median(proud) * 1000), 3),
            "max_proud_mm": round(float(proud.max() * 1000), 3),
            "median_dist_mm": round(float(np.median(d) * 1000), 3),
        }
    json.dump(out, open(os.path.join(work, "lamp_clearance.json"), "w"), indent=1)
    return out


def run(ctx, inp):
    w = ctx.sw("rear")
    lg = ctx.log("rear")
    for d in ("measurements", "build"):
        os.makedirs(os.path.join(w, d), exist_ok=True)
    car = os.path.join(w, "car.glb")
    shutil.copy(inp, car)

    _run([sys.executable, os.path.join(_R2, "fit_panels.py"), car,
          os.path.join(w, "measurements", "fit_report.json")], w, lg)
    _run([sys.executable, os.path.join(_R2, "build_rear.py"), car,
          os.path.join(w, "build")], w, lg)
    raw = os.path.join(w, "rear_raw.glb")
    stripped = os.path.join(w, "rear_stripped.glb")
    _run([sys.executable, os.path.join(_R2, "strip_assemble.py"), car, raw, stripped],
         w, lg)
    out = ctx.p("work", "rear.glb")
    _run([sys.executable, os.path.join(_MACHINE, "gate3v7", "finish.py"), raw,
          ctx.p("in", "car_rebound.glb"), out,
          os.path.join(w, "finish.json")], w, lg, check=False)
    if not os.path.exists(out):
        raise SystemExit("rear stage: finish.py produced no output")
    lc = measure_lamp_clearance(car, out, w)
    print("  rear: melt tail-lamp clearance vs the rebuilt skin:",
          json.dumps({k: v for k, v in lc.items() if k.startswith("TailLamp")}))
    os.remove(raw)
    os.remove(car)
    return out
