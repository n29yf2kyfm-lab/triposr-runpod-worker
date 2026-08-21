"""
respray.py -- the respray control, and the dark-speck / clay-floor measure.

The respray control is the arbiter this project already trusts above every
automated gate: gates + eye + texture all agreed once and all three were wrong,
and only the respray was right. Here it is made per-material rather than
per-eyeball by rendering a MATERIAL-ID pass at the SAME locked camera, so each
pixel's owning material is known exactly and no pixel is attributed by guesswork.

  carpaint  MUST move
  Tyre_Rubber / Rim_Alloy / Lamp_Lens / Lamp_Lens_Rear  MUST NOT move
  glass is EXPECTED to move a little -- it shows the body behind it. Reported,
  not gated, and the gate that matters for glazing is whether the WINDSCREEN
  region moves, which is exactly the defect the glass gate found.
"""
import json
import os
import subprocess
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BL = os.path.join(HERE, 'bl_render.py')


def _run(spec, tag):
    p = os.path.join(HERE, f'spec_{tag}.json')
    json.dump(spec, open(p, 'w'))
    log = os.path.join(HERE, f'logs_{tag}.txt')
    env = dict(os.environ, LIGHT_GAIN=os.environ.get('LIGHT_GAIN', '25'))
    with open(log, 'w') as f:
        subprocess.run(['blender', '-b', '-P', BL, '--', p], stdout=f, stderr=f,
                       cwd=HERE, timeout=5400, env=env)
    ok = 'BL_RENDER_DONE_MARKER' in open(log).read()
    if not ok:
        raise RuntimeError(f'blender did not reach its DONE marker; see {log}')
    return ok


def _rgb(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float64)


def _srgb(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 0), 1 / 2.4) - 0.055)


def matid_palette(mats):
    """Distinct, exactly-recoverable emission colours -- integer steps so the
    label render can be inverted with no tolerance games."""
    pal = {}
    for i, m in enumerate(mats):
        pal[m] = [((i + 1) % 6) / 5.0, ((i + 1) // 6 % 6) / 5.0, ((i + 1) // 36 % 6) / 5.0]
    return pal


def run(glb, tag, views, mats, paint_material='carpaint',
        base_rgb=(0.776, 0.0118, 0.0118), alt_rgb=(0.05, 0.12, 0.75),
        res=900, samples=96, outdir=None):
    out = outdir or os.path.join(HERE, 'rend', tag)
    os.makedirs(out, exist_ok=True)
    pal = matid_palette(mats)
    # 1. material-ID pass (deterministic, 1 sample, AA off)
    _run(dict(glb=glb, res=res, samples=1, mode='label', colours=pal, margin=1.06,
              report=f'{out}/matid.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/matid_{v['name']}.png")
                     for v in views]), tag + '_matid')
    # 2. shaded, base paint
    _run(dict(glb=glb, res=res, samples=samples, margin=1.06,
              paint=dict(material=paint_material, rgb=list(base_rgb)),
              report=f'{out}/base.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/base_{v['name']}.png")
                     for v in views]), tag + '_base')
    # 3. shaded, respray
    _run(dict(glb=glb, res=res, samples=samples, margin=1.06,
              paint=dict(material=paint_material, rgb=list(alt_rgb)),
              report=f'{out}/alt.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/alt_{v['name']}.png")
                     for v in views]), tag + '_alt')
    res_rows = {}
    for v in views:
        mid = _rgb(f"{out}/matid_{v['name']}.png") / 255.0
        A = _rgb(f"{out}/base_{v['name']}.png")
        B = _rgb(f"{out}/alt_{v['name']}.png")
        d = np.abs(A - B).mean(2)
        row = {}
        for m, c in pal.items():
            mask = (np.abs(mid - _srgb(c)[None, None, :]).max(2) < 0.04)
            n = int(mask.sum())
            if n < 30:
                continue
            row[m] = dict(px=n, mean_delta=float(d[mask].mean()),
                          pct_moved_gt10=float(100.0 * (d[mask] > 10).mean()),
                          base_mean_rgb=[float(x) for x in A[mask].mean(0)],
                          alt_mean_rgb=[float(x) for x in B[mask].mean(0)])
        bg = A[:25, :25].reshape(-1, 3).mean(0)
        car = np.abs(A - bg).max(2) > 8
        row['_frame'] = dict(bg_sRGB=float(bg[0]), car_px=int(car.sum()),
                             clipped_pct_of_car=float(100.0 * ((A.max(2) >= 254) & car).sum()
                                                      / max(int(car.sum()), 1)))
        res_rows[v['name']] = row
    json.dump(res_rows, open(f'{out}/respray_measure.json', 'w'), indent=1)
    return res_rows


def dark_specks(glb, tag, zone_views, mats, paint_material='carpaint',
                res=900, samples=96, dark_frac=0.45, outdir=None):
    """Fraction of PAINTED pixels in a zone that read materially darker than the
    zone's own paint level. The CLAY FLOOR -- the same render with every material
    forced to the paint colour -- is measured in the same run, because pure
    shading alone puts some fraction of any curved panel below any threshold and
    a speck count without that floor is meaningless."""
    out = outdir or os.path.join(HERE, 'rend', tag)
    os.makedirs(out, exist_ok=True)
    pal = matid_palette(mats)
    _run(dict(glb=glb, res=res, samples=1, mode='label', colours=pal, margin=1.02,
              report=f'{out}/sk_matid.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/sk_matid_{v['name']}.png")
                     for v in zone_views]), tag + '_skmatid')
    _run(dict(glb=glb, res=res, samples=samples, margin=1.02,
              paint=dict(material=paint_material, rgb=[0.80, 0.80, 0.80]),
              report=f'{out}/sk_shade.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/sk_shade_{v['name']}.png")
                     for v in zone_views]), tag + '_skshade')
    # clay floor: EVERY material rendered at the paint colour
    clay = {m: [0.80, 0.80, 0.80] for m in mats}
    _run(dict(glb=glb, res=res, samples=samples, margin=1.02, mode='clay_shaded',
              paint=dict(material='__ALL__', rgb=[0.80, 0.80, 0.80]),
              clay=clay, report=f'{out}/sk_clay.json',
              views=[dict(az=v['az'], el=v.get('el', 0), out=f"{out}/sk_clay_{v['name']}.png")
                     for v in zone_views]), tag + '_skclay')
    rows = {}
    for v in zone_views:
        mid = _rgb(f"{out}/sk_matid_{v['name']}.png") / 255.0
        S = _rgb(f"{out}/sk_shade_{v['name']}.png").mean(2)
        C = _rgb(f"{out}/sk_clay_{v['name']}.png").mean(2)
        pmask = np.abs(mid - _srgb(pal[paint_material])[None, None, :]).max(2) < 0.04
        z = v.get('crop')
        if z:
            m2 = np.zeros_like(pmask)
            m2[z[0]:z[1], z[2]:z[3]] = True
            pmask = pmask & m2
        anyc = (mid.max(2) > 0.02)
        if z:
            anyc = anyc & m2
        if pmask.sum() < 100:
            rows[v['name']] = dict(px=int(pmask.sum()), note='too few painted px')
            continue
        ref = np.percentile(S[pmask], 75)
        rows[v['name']] = dict(
            painted_px=int(pmask.sum()), ref_level=float(ref),
            dark_pct=float(100.0 * (S[pmask] < dark_frac * ref).mean()),
            clay_floor_pct=float(100.0 * (C[anyc] < dark_frac * np.percentile(C[anyc], 75)).mean()))
    json.dump(rows, open(f'{out}/specks_measure.json', 'w'), indent=1)
    return rows
