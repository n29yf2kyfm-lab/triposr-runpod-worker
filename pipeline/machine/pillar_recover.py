#!/usr/bin/env python3
"""pillar_recover.py — give the B-pillar back. It is not missing, it is glass.

THE DEFECT. The owner said "the b post missing". It is not missing geometry
and it never was — the faces are there and they carry body paint in the
texture. They are LABELLED GLASS, so seg_assemble hands them to the glazing
primitive and the studio rig forces transmission onto them. Measured on the
four-image Golf:

  * each side's glazing is ONE connected component spanning x -1.306 to
    +0.783 — 2.09 m of unbroken glass on a 4.26 m car. A five-door hatch has
    three panes a side, split by the B-pillar and the rear door frame.
  * carpaint faces in the DLO height band peak at the A-pillar (x 0.3-0.9)
    and the C-pillar (x -1.4..-1.2) with nothing between them but drip rail.

WHY DINO DOES THIS. Its "car window" box encloses the whole greenhouse, so
every pillar inside the box is swallowed. It is the lateral twin of the roof
rule already in seg_project: an over-inclusive box, corrected by geometry
the box does not know about.

THE EVIDENCE IS IN THE BAKED TEXTURE, and it is strong. Sampling the mesh's
own baseColorTexture at face-centre UVs across the right-hand DLO:

    x -0.85..-0.45    luma 79-82   (glazing, wide spread)
    x -0.45..-0.35    luma 63.4
    x -0.35..-0.25    luma 53.6    p25 50.9  p75 52.9   <- B-pillar
    x -0.25..-0.15    luma 68.5
    x -0.15.. 0.15    luma 81-82   (glazing again)

A gloss-black pillar reads DARKER than tinted glass in a photograph, and it
reads FLATTER — the pillar's interquartile spread is 2 luma against 20-40
for glass, which picks up sky, interior and reflections. Darkness alone
would be a weak signal on a dark car; darkness AND low variance AND full
DLO height AND narrow in x is not.

SO THE RULE IS FOUR-PART, and every part has to hold:
  1. darker than the pane's own median by MIN_DROP
  2. interquartile spread below MAX_SPREAD (a pillar is one flat colour)
  3. spans at least MIN_HEIGHT_FRAC of the local DLO height
  4. narrower than MAX_WIDTH of the car's length

IT RUNS ON THE LABELLED MESH, BEFORE seg_assemble. That is the whole point:
at this stage the car is one mesh and changing a label moves no geometry and
creates no rim. pane_edge.py tried the same repair downstream on the split
primitives and its own guard refused it twice (+110% and +59% open
boundary), because moving a face between two unwelded shells adds as much
free edge as it fills. Read that file before proposing a downstream fix.

REFUSES if it finds nothing, or if it would take more than MAX_TAKE_FRAC of
the glazing — a rule that eats the windows is wrong, not thorough.

Run: python3 pillar_recover.py <mesh.glb> <labels.npy> <out.npy>
                               [--report r.json] [--dump-profile p.json]
"""
import argparse
import json

import numpy as np
import trimesh

BODY, GLASS = 0, 1            # seg label ids (body/carpaint = 0, glass = 1)

MIN_DROP = 12.0               # luma below the pane median
MAX_SPREAD = 14.0             # p75-p25 within the column
MIN_HEIGHT_FRAC = 0.55        # of the local DLO height
MAX_WIDTH = 0.09              # fraction of car length
MIN_TAKE = 300                # faces; below this it did not find a pillar
MAX_TAKE_FRAC = 0.22          # of the glazing


def face_luma(m):
    uv = getattr(m.visual, "uv", None)
    tex = getattr(getattr(m.visual, "material", None), "baseColorTexture", None)
    if uv is None or tex is None:
        raise SystemExit("REFUSED: this mesh has no baseColorTexture with UVs "
                         "— the pillar evidence lives in the texture, and "
                         "guessing a pillar position instead is exactly the "
                         "kind of assumption this pipeline keeps paying for")
    T = np.asarray(tex.convert("RGB")).astype(np.float32)
    H, W, _ = T.shape
    fuv = uv[m.faces].mean(axis=1)
    px = np.clip((fuv[:, 0] * (W - 1)).astype(int), 0, W - 1)
    py = np.clip(((1 - fuv[:, 1]) * (H - 1)).astype(int), 0, H - 1)
    c = T[py, px]
    return 0.2126 * c[:, 0] + 0.7152 * c[:, 1] + 0.0722 * c[:, 2]


def half_depth_span(x, l, x0, x1, step, med, binw=0.02, depth=0.5):
    """Width of the dark band, read off a fine PROFILE, not off face extremes.

    Taking min/max of every face below the threshold gave 382 mm on a
    128 mm column — a handful of scattered dark faces at the window edges
    set the answer. Bin at 20 mm, threshold at the half-depth between the
    pane median and the band's darkest bin, then keep only the CONTIGUOUS
    run of bins containing that darkest bin. Outliers cannot widen a run
    they are not connected to."""
    w0, w1 = x0 - step, x1 + step
    edges = np.arange(w0, w1 + binw, binw)
    prof, cent = [], []
    for e in edges[:-1]:
        k = (x >= e) & (x < e + binw)
        if k.sum() >= 15:
            prof.append(float(l[k].mean()))
            cent.append(float(e))
    if len(prof) < 3:
        return float(x0), float(x1)
    prof = np.array(prof)
    cent = np.array(cent)
    lo = int(prof.argmin())
    # DEPTH picks how far down the flank to cut. 0.5 is the half-depth
    # crossing, which on this car returns 160-180 mm — the pillar PLUS both
    # door frames plus the darkened glass right at their edge. The owner
    # called that too wide twice, and the eye is the arbiter here: cutting
    # deeper isolates the pillar core. Measured on the Golf, 0.75 lands
    # around 100 mm, which is what a Mk7 B-pillar actually is.
    thr = med - depth * (med - prof[lo])
    i = lo
    while i > 0 and prof[i - 1] < thr:
        i -= 1
    j = lo
    while j < len(prof) - 1 and prof[j + 1] < thr:
        j += 1
    return float(cent[i]), float(cent[j] + binw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh")
    ap.add_argument("labels")
    ap.add_argument("out")
    ap.add_argument("--report", default=None)
    ap.add_argument("--dump-profile", default=None)
    ap.add_argument("--min-drop", type=float, default=MIN_DROP)
    ap.add_argument("--max-spread", type=float, default=MAX_SPREAD)
    ap.add_argument("--depth", type=float, default=0.75,
                    help="how far down the profile flank to cut. 0.5 is the "
                         "half-depth crossing and returns the pillar plus "
                         "both door frames; 0.75 isolates the pillar core.")
    a = ap.parse_args()

    m = trimesh.load(a.mesh, force="mesh", process=False)
    lab = np.load(a.labels)
    if len(lab) != len(m.faces):
        raise SystemExit(f"REFUSED: {len(lab)} labels for {len(m.faces)} faces")
    lum = face_luma(m)
    c, n = m.triangles_center, m.face_normals
    L = float(c[:, 0].max() - c[:, 0].min())
    step = MAX_WIDTH * L / 3.0            # three columns per max pillar width

    taken = np.zeros(len(m.faces), bool)
    profile = {}
    found = []
    for side, sgn in (("R", 1), ("L", -1)):
        # the side glazing, seen edge-on: laterally-facing, off the centreline
        sel = ((lab == GLASS) & (sgn * c[:, 2] > 0.30) &
               (np.abs(n[:, 2]) > 0.45))
        if sel.sum() < 500:
            print(f"  {side}: only {sel.sum()} side-glazing faces — skipped")
            continue
        idx = np.where(sel)[0]
        x, y, l = c[idx, 0], c[idx, 1], lum[idx]
        med = float(np.median(l))
        ylo, yhi = float(np.percentile(y, 2)), float(np.percentile(y, 98))
        dlo = yhi - ylo
        cols = np.arange(x.min(), x.max() + step, step)
        hits, rows = [], []
        for x0 in cols:
            k = (x >= x0) & (x < x0 + step)
            if k.sum() < 40:
                continue
            q25, q75 = np.percentile(l[k], [25, 75])
            drop = med - l[k].mean()
            span = (y[k].max() - y[k].min()) / max(dlo, 1e-6)
            ok = (drop >= a.min_drop and (q75 - q25) <= a.max_spread
                  and span >= MIN_HEIGHT_FRAC)
            rows.append({"x": round(float(x0), 3), "n": int(k.sum()),
                         "drop": round(float(drop), 1),
                         "spread": round(float(q75 - q25), 1),
                         "height_frac": round(float(span), 2), "hit": bool(ok)})
            if ok:
                hits.append(x0)
        profile[side] = {"median_luma": round(med, 1), "columns": rows}
        if not hits:
            print(f"  {side}: no column met all four tests")
            continue
        # group adjacent hit columns into pillars
        hits = np.array(sorted(hits))
        grp = np.split(hits, np.where(np.diff(hits) > step * 1.5)[0] + 1)
        for g in grp:
            x0, x1 = g.min(), g.max() + step
            if (x1 - x0) > MAX_WIDTH * L:
                print(f"  {side}: band {x0:.2f}..{x1:.2f} is "
                      f"{(x1-x0)/L:.1%} of length — too wide for a pillar, "
                      f"rejected")
                continue
            # THE COLUMN LOCATES THE PILLAR; PER-FACE LUMA DELIMITS IT.
            # Taking the whole hit column made the pillar exactly one column
            # wide — 128 mm on this car — which is the detector's own
            # resolution, not a measurement, and the owner saw it straight
            # away ("the b pillar is too wide, out of proportion"). Widen
            # the window by a column each side, then cut at the HALF-DEPTH
            # crossing between the pane median and the band's dark core,
            # which is the standard way to read a feature's width off a
            # profile. Same shape as every other rule here: the cheap test
            # finds the candidate, a finer measurement gives the verdict.
            fx0, fx1 = half_depth_span(x, l, x0, x1, step, med,
                                       depth=a.depth)
            fine = (x >= fx0) & (x < fx1)
            if fine.sum() < 40:
                print(f"  {side}: half-depth cut left {int(fine.sum())} "
                      f"faces — falling back to the column")
                fine = (x >= x0) & (x < x1)
                fx0, fx1 = x0, x1
            k = idx[fine]
            taken[k] = True
            found.append((side, fx0, fx1))
            print(f"  {side}: pillar x {fx0:6.3f}..{fx1:6.3f} "
                  f"({1000*(fx1-fx0):.0f} mm measured, column was "
                  f"{1000*(x1-x0):.0f} mm) -> {len(k)} faces")

    # SYMMETRY PROPOSES, EVIDENCE CONFIRMS. A car is symmetric, so a pillar
    # found on one flank has a twin on the other. Measured on the Golf, the
    # right B-pillar is unmistakable (drop 13.6, spread 3.0) while the left
    # one at the mirrored position scores drop 12.0, spread 15.0 and misses
    # the spread test by a single luma - the left flank sits under the rig's
    # key light and its glazing reflects more, which widens every column's
    # spread on that side. Relaxing the threshold globally to catch it would
    # let real glazing columns through; asking the OTHER side, at the
    # position its twin was found, does not. The mirror only proposes a
    # place to look - the column still has to show half the drop, or it is
    # refused.
    if len(found) == 1:
        side, x0, x1 = found[0]
        other = "L" if side == "R" else "R"
        sgn = -1 if other == "L" else 1
        sel = ((lab == GLASS) & (sgn * c[:, 2] > 0.30) &
               (np.abs(n[:, 2]) > 0.45))
        idx = np.where(sel)[0]
        if sel.sum() >= 500:
            x, l = c[idx, 0], lum[idx]
            med = float(np.median(l))
            win = (x >= x0 - step) & (x < x1 + step)
            k = (x >= x0) & (x < x1)
            if k.sum() >= 40:
                drop = med - l[k].mean()
                if drop >= a.min_drop * 0.5:
                    fx0, fx1 = half_depth_span(x, l, x0, x1, step, med,
                                               depth=a.depth)
                    fine = (x >= fx0) & (x < fx1)
                    if fine.sum() < 40:
                        fine, fx0, fx1 = k, x0, x1
                    taken[idx[fine]] = True
                    found.append((other, fx0, fx1))
                    print(f"  {other}: mirrored pillar CONFIRMED (drop "
                          f"{drop:.1f}) x {fx0:6.3f}..{fx1:6.3f} "
                          f"({1000*(fx1-fx0):.0f} mm) -> "
                          f"{int(fine.sum())} faces")
                else:
                    print(f"  {other}: mirrored position shows drop "
                          f"{drop:.1f} — not confirmed, left as glass")

    ng = int((lab == GLASS).sum())
    print(f"\nglazing faces {ng}; recovered to body {int(taken.sum())} "
          f"({100*taken.sum()/max(ng,1):.1f}%)")
    if taken.sum() < MIN_TAKE:
        raise SystemExit(f"REFUSED: only {int(taken.sum())} faces met the "
                         f"four-part test — no pillar found, and writing an "
                         f"unchanged copy would be a no-op dressed as a fix")
    if taken.sum() > MAX_TAKE_FRAC * ng:
        raise SystemExit(f"REFUSED: would take {100*taken.sum()/ng:.1f}% of "
                         f"the glazing — a rule that eats the windows is "
                         f"wrong, not thorough")

    out = lab.copy()
    out[taken] = BODY
    np.save(a.out, out)
    print(f"wrote {a.out}")
    if a.report:
        # the BANDS go in the report so pillar_material.py can find the
        # pillar again on the assembled file by GEOMETRY. Face indices are
        # useless downstream — blender_finish welds and re-indexes.
        yy = c[taken][:, 1]
        json.dump({"recovered": int(taken.sum()), "glass_before": ng,
                   "glass_after": int((out == GLASS).sum()),
                   "y_lo": float(np.percentile(yy, 1)),
                   "y_hi": float(np.percentile(yy, 99)),
                   "bands": [{"side": sd, "x0": round(p0, 4),
                              "x1": round(p1, 4),
                              "width_mm": round(1000 * (p1 - p0))}
                             for sd, p0, p1 in found]},
                  open(a.report, "w"), indent=1)
    if a.dump_profile:
        json.dump(profile, open(a.dump_profile, "w"), indent=1)


if __name__ == "__main__":
    main()
