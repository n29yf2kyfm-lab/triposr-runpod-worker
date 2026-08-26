#!/usr/bin/env python3
"""glass_where.py — WHERE is the labelled glazing, not how much of it there is.

THE GAP THIS FILLS. Every glazing instrument in this repo answers a different
question and all of them pass a van whose cargo box has been glazed:

  * glass_probe    — is the glazing MATERIAL transparent?  (reads the material
                     table; blind to which faces carry it — three recorded
                     blind spots, CLAUDE.md 2026-08-21)
  * the band gate  — is glass AREA between 1.0 and 13.0% of the car?
  * glass_topo     — is each pane ONE component with ONE boundary loop?

A Ford Transit Custom PANEL van labelled with windows down its cargo flanks
passes all three. Measured on the TRELLIS.2 control 2026-08-26: material BLEND
alpha 0.353 (clear), area 12.5% (inside the band), and 36.5% of that area
sitting in the rear third of a van whose raw texture shows a SOLID white cargo
panel there. Material, area and integrity are each necessary; POSITION is a
fourth question none of them asks.

WHY IT REPORTS AND DOES NOT GATE. A rear-third concentration is a real defect on
a panel van and completely normal on a Tourneo, a minibus, an estate or any car
with a rear quarter-light. There is no threshold that separates those from the
body style alone, and this project has been burned repeatedly by candidate
finders promoted to verdicts (the tyre-darkness probe that "confidently said all
clear", the rim luma screen that flagged every car). So: print the distribution,
flag the concentration, and let the eye and the body style decide.

NOSE DIRECTION IS TAKEN FROM THE LAMPS AND IS REFUSED WHEN AMBIGUOUS. Deciding
it from the glazing would be circular — the glazing is the thing under test,
exactly the circularity that made a label-derived pose check "prove" a car was
upright while it lay on its side (CLAUDE.md 2026-08-19). If the lamp label sits
at both ends, or there is no lamp label, this prints UNORIENTED deciles and says
so rather than guessing which end is the front.

Run:
  python3 glass_where.py car_final.glb [--glass-node glass] [--json out.json]
"""
import argparse
import json
import os
import sys

import numpy as np
import trimesh

# A lamp centroid this far from either end means head and tail lamps are both
# labelled and their mean is meaningless as a nose marker.
NOSE_MIN_FRAC = 0.75


def _area_weights(v, f):
    """Triangle areas. Area, never face COUNT — face count is tessellation-
    dependent, which is the error that made the old glass band gate wrong
    (CLAUDE.md 2026-08-19: glass faces measured 1.58x smaller than body faces)."""
    tri = v[f]
    return np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                   tri[:, 2] - tri[:, 0]), axis=1) / 2.0


def analyse(path, glass_node="glass", lamp_node="Lamp_Lens"):
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    sc = trimesh.load(path, process=False)
    geoms = dict(sc.geometry)
    if glass_node not in geoms:
        raise SystemExit(f"no '{glass_node}' node; have {sorted(geoms)}")

    allv = np.vstack([np.asarray(g.vertices) for g in geoms.values()])
    lo, hi = allv.min(0), allv.max(0)
    ext = hi - lo
    ax = int(np.argmax(ext))                       # length axis, measured

    g = geoms[glass_node]
    v, f = np.asarray(g.vertices), np.asarray(g.faces)
    tri = v[f]
    cen = tri.mean(1)
    frac = (cen[:, ax] - lo[ax]) / ext[ax]
    w = _area_weights(v, f)

    # nose from the LAMPS, and only when they are unambiguous
    nose_end, nose_frac, why = None, None, "no lamp node"
    if lamp_node in geoms:
        lv = np.asarray(geoms[lamp_node].vertices)
        nose_frac = float((lv.mean(0)[ax] - lo[ax]) / ext[ax])
        if nose_frac >= NOSE_MIN_FRAC:
            nose_end, why = "high", f"lamp centroid {nose_frac:.3f} >= {NOSE_MIN_FRAC}"
        elif nose_frac <= 1 - NOSE_MIN_FRAC:
            nose_end, why = "low", f"lamp centroid {nose_frac:.3f} <= {1-NOSE_MIN_FRAC}"
        else:
            why = (f"lamp centroid {nose_frac:.3f} is mid-body — head and tail "
                   "lamps both labelled, so it cannot mark the nose")

    # ROOF SHARE — the one glazing-placement test that needs no body style.
    # No production vehicle has a glass roof unless it is a panoramic roof, and
    # a panel van certainly does not, so up-facing glazing high on the car is
    # wrong for ANY input and needs no Tourneo-vs-panel-van judgement. Added
    # after a reviewer caught the machine glazing the roof and cargo flank of
    # the Pixal van2 while the rear-third gate read 3.16% and stayed silent:
    # measured 64.52% of glazing up-facing and 29.61% in the roof zone.
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nrm = nrm / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
    yfrac = (cen[:, 1] - lo[1]) / ext[1]
    up = np.abs(nrm[:, 1]) > 0.7
    up_pct = float(w[up].sum() / w.sum() * 100)
    roof_pct = float(w[yfrac > 0.85].sum() / w.sum() * 100)

    dec = [float(w[(frac >= i / 10) & (frac < (i + 1) / 10)].sum() / w.sum() * 100)
           for i in range(10)]
    # Report nose-first. Deciles are built low-frac -> high-frac, so the REVERSE
    # is needed when the nose sits at HIGH frac. Getting this backwards printed
    # a 27.4% windscreen decile as "rear third" on the van control and still
    # fired the flag — a check that fires for the wrong reason is the least
    # visible kind of broken instrument (CLAUDE.md). Fenced by selftest below.
    if nose_end == "high":
        dec = dec[::-1]

    out = {"file": path, "length_axis": ax,
           "glass_up_facing_pct": round(up_pct, 2),
           "glass_roof_zone_pct": round(roof_pct, 2),
           "extents": [round(float(x), 4) for x in ext],
           "glass_area": round(float(w.sum()), 5),
           "nose_end": nose_end, "nose_evidence": why,
           "deciles_nose_to_tail" if nose_end else "deciles_UNORIENTED":
               [round(d, 2) for d in dec]}
    if nose_end:
        # front third = cabin + windscreen on any body style; rear third is
        # where a PANEL van must have none and a Tourneo legitimately has a lot
        out["front_third_pct"] = round(sum(dec[:3]), 2)
        out["mid_third_pct"] = round(sum(dec[3:7]), 2)
        out["rear_third_pct"] = round(sum(dec[7:]), 2)
        # BEHIND-CABIN is the number that matters on a van, and gating the rear
        # third alone MISSED A REAL DEFECT. On the Pixal van2 the machine glazed
        # the cargo flank and it landed in the MID third: rear was 3.16% (no
        # flag) while mid was 27.21%, of which 100% sat above the beltline and
        # 77.8% on one flank — a window band down a panel van's cargo side.
        # A van's cargo box spans mid AND rear; a cabin ends around 0.35 of the
        # length. Caught by a reviewer, not by this tool, which is why the tool
        # now reports it.
        out["behind_cabin_pct"] = round(sum(dec[4:]), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--glass-node", default="glass")
    ap.add_argument("--lamp-node", default="Lamp_Lens")
    ap.add_argument("--json")
    a = ap.parse_args()

    r = analyse(a.glb, a.glass_node, a.lamp_node)
    print(f"length axis {r['length_axis']}  extents {r['extents']}")
    print(f"glass up-facing {r['glass_up_facing_pct']}%   "
          f"in roof zone (top 15% of height) {r['glass_roof_zone_pct']}%")
    if r["glass_up_facing_pct"] > 35 or r["glass_roof_zone_pct"] > 12:
        print("  FLAG: the ROOF is carrying glass label. No body style has a "
              "glass roof bar a panoramic one — this needs no van-vs-Tourneo\n"
              "  judgement and is wrong for any input.")
    print(f"nose: {r['nose_end'] or 'UNKNOWN'}  ({r['nose_evidence']})")
    key = "deciles_nose_to_tail" if r["nose_end"] else "deciles_UNORIENTED"
    print(f"\nGLASS AREA by decile ({'nose -> tail' if r['nose_end'] else 'UNORIENTED'}):")
    for i, d in enumerate(r[key]):
        print(f"  {i/10:.1f}-{(i+1)/10:.1f}  {d:6.2f}%  {'#' * int(d / 2)}")
    if r["nose_end"]:
        print(f"\nfront {r['front_third_pct']}%   mid {r['mid_third_pct']}%   "
              f"rear {r['rear_third_pct']}%")
        print(f"behind cabin (from 0.4 of length back): {r['behind_cabin_pct']}%")
        if r["behind_cabin_pct"] > 15:
            print("\nFLAG (candidate, NOT a verdict): a large share of the "
                  "glazing sits BEHIND THE CABIN.\n"
                  "  Correct on a Tourneo/minibus/estate or any car with rear "
                  "side glass.\n"
                  "  WRONG on a panel van — check the SOURCE texture on that "
                  "flank, and run a matID render before accepting it.\n"
                  "  Gating the REAR THIRD alone missed exactly this: a glazed "
                  "cargo flank can sit in the MID third and score 3.16% at the "
                  "rear.")
    else:
        print("\nnose direction not established — deciles are unoriented and "
              "front/rear cannot be reported. Refusing to guess.")
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def _selftest():
    """Both directions, on synthetic cars whose answers are known by construction.

    The orientation bug this fences reported a windscreen decile as "rear third"
    AND STILL FIRED THE FLAG, so a pass/fail on the real van could not have
    caught it. These cases pin the decile ORDER, not just the verdict.
    """
    import tempfile, os
    def build(glass_fracs, lamp_frac, path):
        """A car 1.0 long on x; glass quads at the given length fractions."""
        meshes = {}
        def quad(fr, w=0.02):
            x = fr
            v = np.array([[x, .2, -.1], [x + w, .2, -.1],
                          [x + w, .3, -.1], [x, .3, -.1]], float)
            return v, np.array([[0, 1, 2], [0, 2, 3]])
        gv, gf = [], []
        for fr in glass_fracs:
            v, f = quad(fr)
            gf.append(f + len(gv) * 4); gv.append(v)
        meshes["glass"] = trimesh.Trimesh(np.vstack(gv), np.vstack(gf), process=False)
        lv, lf = quad(lamp_frac)
        meshes["Lamp_Lens"] = trimesh.Trimesh(lv, lf, process=False)
        # body spans the full length so the length axis and extents are honest
        body = trimesh.creation.box(extents=[1.0, .4, .4])
        body.apply_translation([.5, .2, 0])
        meshes["carpaint"] = body
        sc = trimesh.Scene(meshes); sc.export(path)

    ok = True
    with tempfile.TemporaryDirectory() as d:
        # nose at HIGH x: glass bunched near x=0.9 must read as FRONT third
        p = os.path.join(d, "hi.glb")
        build([0.88, 0.90, 0.92], 0.95, p)
        r = analyse(p)
        hit = r["nose_end"] == "high" and r["front_third_pct"] > 90
        print(f"  nose HIGH  -> nose={r['nose_end']} front={r['front_third_pct']}% "
              f"rear={r['rear_third_pct']}%  {'OK' if hit else 'FAIL'}")
        ok &= hit

        # nose at LOW x: glass bunched near x=0.1 must ALSO read as FRONT third
        p = os.path.join(d, "lo.glb")
        build([0.06, 0.08, 0.10], 0.03, p)
        r = analyse(p)
        hit = r["nose_end"] == "low" and r["front_third_pct"] > 90
        print(f"  nose LOW   -> nose={r['nose_end']} front={r['front_third_pct']}% "
              f"rear={r['rear_third_pct']}%  {'OK' if hit else 'FAIL'}")
        ok &= hit

        # glass at the far end from the lamps must read as REAR third, both ways
        p = os.path.join(d, "hi_rear.glb")
        build([0.06, 0.08, 0.10], 0.95, p)
        r = analyse(p)
        hit = r["nose_end"] == "high" and r["rear_third_pct"] > 90
        print(f"  cargo-glazed (nose HIGH) -> rear={r['rear_third_pct']}%  "
              f"{'OK' if hit else 'FAIL'}")
        ok &= hit

        p = os.path.join(d, "lo_rear.glb")
        build([0.88, 0.90, 0.92], 0.03, p)
        r = analyse(p)
        hit = r["nose_end"] == "low" and r["rear_third_pct"] > 90
        print(f"  cargo-glazed (nose LOW)  -> rear={r['rear_third_pct']}%  "
              f"{'OK' if hit else 'FAIL'}")
        ok &= hit

        # lamps at BOTH ends -> must REFUSE to orient rather than guess
        p = os.path.join(d, "amb.glb")
        build([0.5], 0.5, p)
        r = analyse(p)
        hit = r["nose_end"] is None and "front_third_pct" not in r
        print(f"  ambiguous lamps -> nose={r['nose_end']} (refused)  "
              f"{'OK' if hit else 'FAIL'}")
        ok &= hit
    return ok
