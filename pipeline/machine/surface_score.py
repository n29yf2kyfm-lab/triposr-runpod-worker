#!/usr/bin/env python3
"""surface_score.py — score repair variants against the SAME fixed face set.

WHY THIS EXISTS RATHER THAN JUST RUNNING surface_metric ON EACH FILE. The
metric restricts itself to "panel" faces, defined as the region minus a feature
mask that is recomputed from the mesh being measured. That is right for
measuring one car and WRONG for comparing a repair to its input: a repair
changes the dihedral angles, so it changes its own feature mask, so it changes
which faces it is scored on. A variant can then improve its number by moving
faces out of its own scoreboard. Here the panel mask, the feature mask and the
region masks are computed ONCE on the BASELINE and every variant is scored on
those same face indices.

It also scores on the GEOMETRIC exterior-panel selection from body_surface.py
rather than on a material name, because on this car the material names do not
delimit the body (`interior` holds 45% of the exterior body panel area,
including the sills and the front bumper).

Reported per region, and all four numbers matter together:

  s25   sigma_theta at 25 mm, degrees — the ROUGHNESS band. Triangle chatter
        and scan grain. This is the band that shatters a zebra line.
  s80   sigma_theta at 80 mm, degrees — the WAVINESS band. Broad dents, bonnet
        undulation, panel swelling.
  C25   coherence of the 25 mm residuals. +1 = neighbouring faces lean the same
        way, which is what a real feature does; 0 = uncorrelated noise;
        negative = alternating ripple. THE MAGNITUDE ALONE IS THE WRONG
        QUESTION — calibration against 14 catalogue cars showed the generated
        Golf scoring a LOWER sigma than every real car, because a real car's
        normal field deviates from a local quadric through deliberate
        hard-surface detail and those deviations are ORGANISED.
  crease total length of edges sharper than 35 deg, metres. Printed beside the
        quality numbers because the obvious way to win them is to destroy the
        shut lines, and that trade is visible here and nowhere else.

Run:
  python3 surface_score.py <baseline.glb> [variant.glb ...] --select sel.npz
        [--regions flank,roof,bonnet,all] [--max-faces 60000] [--json out.json]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import body_surface as bs           # noqa: E402
import surface_metric as sm         # noqa: E402
import panel_reform as pr           # noqa: E402


def load_welded(path):
    car = bs.Car(path)
    return car


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glbs", nargs="+")
    ap.add_argument("--select", required=True)
    ap.add_argument("--regions", default="all,flank,roof,bonnet")
    ap.add_argument("--radii", default="0.025,0.080")
    ap.add_argument("--max-faces", type=int, default=60000)
    ap.add_argument("--crease-deg", type=float, default=35.0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    radii = [float(x) for x in a.radii.split(",")]
    regions = a.regions.split(",")

    base = load_welded(a.glbs[0])
    sel = np.load(a.select, allow_pickle=True)
    panel_sel = sel["panel"]
    if len(panel_sel) != len(base.Fw):
        raise SystemExit(f"REFUSED: selection has {len(panel_sel)} faces, "
                         f"baseline weld has {len(base.Fw)}")
    fp = str(sel["fingerprint"]) if "fingerprint" in sel else None
    if fp != base.fingerprint:
        raise SystemExit(f"REFUSED: selection fingerprint {fp} != baseline "
                         f"weld {base.fingerprint}. Re-run body_surface.py.")

    # ---- masks computed ONCE, on the baseline, and never recomputed
    mesh0 = base.mesh
    feat0 = sm.feature_mask(mesh0)
    masks = {}
    for r in regions:
        rm = sm.region_mask(mesh0, r)
        masks[r] = rm & panel_sel & ~feat0
        print(f"  region {r:7s}: {int(masks[r].sum()):7d} scored faces "
              f"(of {int((rm & panel_sel).sum())} exterior-panel in region)")
    il, iw, iu = sm.car_axes(mesh0)
    print(f"  axes: length={il} width={iw} up={iu}   "
          f"baseline extents {np.round(mesh0.extents,3)}")

    rows = []
    for p in a.glbs:
        t0 = time.time()
        if p == a.glbs[0]:
            Vw = base.Vw
        else:
            car = load_welded(p)
            try:
                # Re-weld in the BASELINE's ordering. Welding the variant
                # independently would order its vertices by their own moved
                # coordinates and pair unrelated vertices — see
                # body_surface.Car.rewelded_like.
                Vw = car.rewelded_like(base)
            except ValueError as exc:
                print(f"  {os.path.basename(p)}: REFUSED — {exc}")
                continue
        m = trimesh.Trimesh(vertices=Vw, faces=base.Fw, process=False)
        d = np.linalg.norm(Vw - base.Vw, axis=1)
        cl = pr.crease_length(m, a.crease_deg)
        row = dict(file=os.path.basename(p), crease_m=round(cl, 2),
                   disp_mean_mm=round(float(d.mean()) * 1000, 3),
                   disp_max_mm=round(float(d.max()) * 1000, 2), regions={})
        for r in regions:
            rr = {}
            for R in radii:
                s = sm.slope_error(m, R, mask=masks[r], max_faces=a.max_faces)
                rr[f"{int(R*1000)}mm"] = s
            row["regions"][r] = rr
        rows.append(row)
        print(f"\n{os.path.basename(p)}  crease={cl:.1f}m  "
              f"disp mean={row['disp_mean_mm']}mm max={row['disp_max_mm']}mm "
              f"[{time.time()-t0:.0f}s]")
        for r in regions:
            rr = row["regions"][r]
            bits = []
            for R in radii:
                k = f"{int(R*1000)}mm"
                s = rr[k]
                c = s.get("coherence")
                bits.append(f"s{int(R*1000)}={s.get('rms',float('nan')):6.3f} "
                            f"C{int(R*1000)}={c if c is not None else '  --  '}")
            print(f"    {r:7s} " + "  ".join(str(b) for b in bits))

    # ---- delta table against the baseline
    if len(rows) > 1:
        b = rows[0]
        print("\n=== CHANGE vs BASELINE ===")
        hdr = f"{'file':28s} {'crease':>9s}"
        for r in regions:
            hdr += f" {r+' s25':>12s} {r+' C25':>12s} {r+' s80':>12s}"
        print(hdr)
        for row in rows:
            line = f"{row['file'][:28]:28s} " \
                   f"{row['crease_m']:6.1f}m" \
                   f"{(row['crease_m']-b['crease_m'])/max(b['crease_m'],1e-9)*100:+5.1f}%"
            for r in regions:
                for k in ("25mm", "25mmC", "80mm"):
                    if k == "25mmC":
                        v = row["regions"][r]["25mm"].get("coherence")
                        v0 = b["regions"][r]["25mm"].get("coherence")
                        line += f" {v if v is not None else float('nan'):6.3f}" \
                                f"{(v-v0) if (v is not None and v0 is not None) else float('nan'):+6.3f}"
                    else:
                        v = row["regions"][r][k].get("rms", float("nan"))
                        v0 = b["regions"][r][k].get("rms", float("nan"))
                        line += f" {v:6.3f}{(v-v0)/max(v0,1e-9)*100:+6.1f}%"
            print(line)

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(dict(select=a.select, regions=regions, rows=rows), fh,
                      indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
