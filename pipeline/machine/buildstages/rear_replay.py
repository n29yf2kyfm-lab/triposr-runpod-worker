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
    # `Glass_Rear` IS NOT KEPT, and that was a real bug in the first run of this
    # replay.  Sparing every `Glass_*` node left the MELT rear screen standing
    # inside the rebuilt tailgate: the constructed `Glass_Backlight` came out
    # 96.8% within 25 mm of it at a median of 6.0 mm — two transmissive sheets
    # in the same place, which is the recorded WHITE-DOT DEFECT that cost six
    # wrong theories the last time it appeared.  Gate 4's own file does not keep
    # its `Rear_Glass` either; the strip cuts it in the panel footprint like any
    # other surface, and the constructed pane then fills the constructed
    # aperture.  The front and side panes ARE kept: the bumper footprint sweeps
    # to +-88 deg and could otherwise reach them.
    "REAR2_KEEP": ",".join([
        "Wheel_", "TailLamp_", "Headlamp_", "Mirror_",
        "Glass_Windscreen", "Glass_Side", "Glass_Quarter", "Cabin_",
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
    lamps = [n for n in sc.graph.nodes_geometry
             if n.startswith(("TailLamp", "Tail_Lens", "Tail_Housing"))]
    for lam in lamps:
        L = W(lam)
        d, i = tree.query(L, k=1, workers=2)
        # signed: outboard (larger x than the nearest panel vertex) = proud
        proud = L[:, 0] - PV[i][:, 0]
        # CORRECTION 2026-08-21, made after the first run reported "37-38% of
        # lamp vertices buried, minimum -111/-140 mm" and I nearly wrote that
        # down as a defect.  It was MY OWN PROXY that was wrong.  `TailLamp_L`
        # spans z -0.827..+0.004 while the rebuilt `Hatch` spans -0.721..+0.569,
        # so 106 mm of each lamp lies on the QUARTER PANELS, which this gate
        # does not rebuild.  Comparing those vertices against "the nearest
        # rebuilt-panel vertex" measures the distance to a panel that is not
        # there: 97.7% of the L lamp's supposedly-buried vertices are at
        # |z| > 0.60, i.e. outside the tailgate entirely.  The clearance figure
        # is only meaningful where the panel actually covers the lamp, so it is
        # restricted to vertices whose nearest panel vertex is within LAT_TOL
        # laterally, and the out-of-footprint share is reported separately
        # rather than counted as burial.
        LAT_TOL = 0.015
        lat = np.linalg.norm(L[:, 1:] - PV[i][:, 1:], axis=1)
        cov = lat < LAT_TOL
        pc = proud[cov]
        out[lam] = {
            "verts": int(len(L)),
            "in_panel_footprint_pct": round(float(100 * cov.mean()), 2),
            "outside_footprint_note": "on the quarters, which this gate does not rebuild",
            "buried_pct_in_footprint": (round(float(100 * (pc < -0.002).mean()), 3)
                                        if cov.sum() else None),
            "min_proud_mm_in_footprint": (round(float(pc.min() * 1000), 3)
                                          if cov.sum() else None),
            "median_proud_mm_in_footprint": (round(float(np.median(pc) * 1000), 3)
                                             if cov.sum() else None),
            "max_proud_mm_in_footprint": (round(float(pc.max() * 1000), 3)
                                          if cov.sum() else None),
            "median_dist_mm_all": round(float(np.median(d) * 1000), 3),
            "raw_all_verts_buried_pct_PROXY": round(float(100 * (proud < -0.002).mean()), 3),
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
    # Gate 4's four constructed tail-lamp units, transplanted, and the melt
    # lamps they replace deleted in the same operation.  See lamp_transplant.py
    # for why this is a transplant where the PANELS were a replay.
    import lamp_transplant
    donor = os.environ.get("REAR2_LAMP_DONOR")
    if donor and os.path.exists(donor):
        withlamps = os.path.join(w, "rear_lamps.glb")
        lr = lamp_transplant.run(out, donor, withlamps,
                                 os.path.join(w, "lamp_transplant.json"))
        os.replace(withlamps, out)
        print("  rear: transplanted", len(lr["added"]), "lamp units, dropped",
              list(lr["dropped"]), "| materials added", lr["materials_added"])
    else:
        print("  rear: NO LAMP DONOR -- the four constructed units are NOT "
              "present and the melt TailLamp_L/R stand in for them")
    lc = measure_lamp_clearance(car, out, w)
    print("  rear: melt tail-lamp clearance vs the rebuilt skin:",
          json.dumps({k: v for k, v in lc.items() if k.startswith("TailLamp")}))
    os.remove(raw)
    os.remove(car)
    return out
