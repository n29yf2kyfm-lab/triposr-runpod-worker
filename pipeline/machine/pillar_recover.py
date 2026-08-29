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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh")
    ap.add_argument("labels")
    ap.add_argument("out")
    ap.add_argument("--report", default=None)
    ap.add_argument("--dump-profile", default=None)
    ap.add_argument("--min-drop", type=float, default=MIN_DROP)
    ap.add_argument("--max-spread", type=float, default=MAX_SPREAD)
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
            k = idx[(x >= x0) & (x < x1)]
            taken[k] = True
            print(f"  {side}: pillar x {x0:6.3f}..{x1:6.3f} "
                  f"({1000*(x1-x0):.0f} mm) -> {len(k)} faces to body")

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
        json.dump({"recovered": int(taken.sum()), "glass_before": ng,
                   "glass_after": int((out == GLASS).sum())},
                  open(a.report, "w"), indent=1)
    if a.dump_profile:
        json.dump(profile, open(a.dump_profile, "w"), indent=1)


if __name__ == "__main__":
    main()
