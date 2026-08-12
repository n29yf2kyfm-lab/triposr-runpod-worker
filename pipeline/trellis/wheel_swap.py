#!/usr/bin/env python3
"""wheel_swap.py — replace generated melt wheels with a library wheel.

Generated wheels are always the weakest part of a hybrid car. This stage
overlays crisp wheel geometry harvested from an audited catalogue car
(default donor: the GR Supra's front-left wheel, 13,633 verts) onto the
hybrid GLB produced by hybrid_transfer.py.

Method, each choice paid for on the 2026-08-12 test car:
  * The original wheel-labeled faces are KEPT and recoloured to a near-black
    Arch_Cavity material — deleting them punches holes in the watertight
    shell, and a dark cavity behind the new wheel reads as shadow, which is
    what a real arch looks like.
  * Wheel positions come from the tyre-zone faces only (below ground+0.30),
    clustered by quadrant — the wheel LABEL's bbox is a trap: it includes
    arch-liner spill, which mis-centred and 40%-oversized the first attempt
    (dia 0.60 from the label vs 0.44-0.50 honest).
  * Wheel depth comes from the BODY's side surface at that axle (98th pct of
    width), outer face 12mm inboard — not from the label patch.
  * The donor's own materials are NOT trusted (the Supra ships its whole
    wheel as one pale "wheel_rim" material). The donor contributes GEOMETRY
    only; tyre/rim are split by radius (>72% R = tyre) and get our own
    Tyre_Rubber / Rim_Alloy materials, so the tyre rule holds by
    construction.
  * Draco donors must be decompressed first (gltf-transform copy) — both
    Blender and trimesh here lack a Draco decoder.

Usage:
    python3 pipeline/trellis/wheel_swap.py \
        --car hybrid.glb --donor donor_uc.glb \
        --donor-geom Wheel_01_LF_Wheel1A_0 --dia 0.46 --out car_wheels.glb
"""
import argparse

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

TYRE_MAT = dict(name="Tyre_Rubber", baseColorFactor=[0.028, 0.028, 0.030, 1.0],
                metallicFactor=0.0, roughnessFactor=0.9)
RIM_MAT = dict(name="Rim_Alloy", baseColorFactor=[0.42, 0.43, 0.45, 1.0],
               metallicFactor=0.85, roughnessFactor=0.35)
CAVITY_MAT = dict(name="Arch_Cavity", baseColorFactor=[0.015, 0.015, 0.016, 1.0],
                  metallicFactor=0.0, roughnessFactor=1.0)


def load_donor(path, geom_name, tyre_frac=0.72):
    """Donor wheel centred at origin, axis +X, split into (tyre, rim)."""
    s = trimesh.load(path)
    donor = s.geometry[geom_name].copy()
    ctr = (donor.vertices.max(0) + donor.vertices.min(0)) / 2
    donor.vertices -= ctr
    R = np.abs(donor.vertices[:, 1:3]).max()
    fc_r = np.linalg.norm(donor.triangles_center[:, 1:3], axis=1)
    tyre = donor.submesh([np.where(fc_r > tyre_frac * R)[0]], append=True)
    rim = donor.submesh([np.where(fc_r <= tyre_frac * R)[0]], append=True)
    tyre.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(**TYRE_MAT))
    rim.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(**RIM_MAT))
    wid = donor.vertices[:, 0].max() - donor.vertices[:, 0].min()
    return tyre, rim, 2 * R, wid


def swap(car_glb, donor_glb, donor_geom, out_glb, dia=0.46):
    tyre, rim, d_dia, d_wid = load_donor(donor_glb, donor_geom)
    w = trimesh.load(car_glb)
    if "wheel" not in w.geometry:
        raise SystemExit("no 'wheel' geometry in the car GLB — run "
                         "hybrid_transfer.py first")
    body = w.geometry["body"]
    wheel = w.geometry["wheel"]
    allv = np.concatenate([g.vertices for g in w.geometry.values()])
    ground_y = np.percentile(allv[:, 1], 0.4)
    len_mid = allv[:, 0].mean()
    wid_mid = allv[:, 2].mean()

    wheel.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(**CAVITY_MAT))

    low = wheel.triangles_center
    low = low[low[:, 1] < ground_y + 0.30]

    out = trimesh.Scene()
    for name, g in w.geometry.items():
        out.add_geometry(g, node_name=name, geom_name=name)
    placed = 0
    for i, (sl, sw) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        q = low[((low[:, 0] - len_mid) * sl > 0) & ((low[:, 2] - wid_mid) * sw > 0)]
        if len(q) < 20:
            print(f"corner {i}: no tyre-zone faces — skipped")
            continue
        cx = np.median(q[:, 0])
        band = body.vertices[np.abs(body.vertices[:, 0] - cx) < 0.2]
        outer = np.percentile(band[:, 2], 98 if sw > 0 else 2)
        sc = dia / d_dia
        for part, nm in ((tyre, "tyre"), (rim, "rim")):
            inst = part.copy()
            inst.apply_scale(sc)
            ang = np.pi / 2 if sw > 0 else -np.pi / 2
            inst.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 1, 0]))
            inst.apply_translation([cx, ground_y + dia / 2,
                                    (outer - sw * 0.012) - sw * (d_wid * sc) / 2])
            out.add_geometry(inst, node_name=f"lib_{nm}_{i}", geom_name=f"lib_{nm}_{i}")
        placed += 1
        print(f"corner {i}: len={cx:.2f} side={sw:+d} outer={outer:.2f}")
    if placed < 4:
        raise SystemExit(f"only {placed}/4 wheels placed — refusing to write "
                         "a three-wheeled car")
    out.export(out_glb)
    print(f"WROTE {out_glb}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--car", required=True, help="hybrid GLB with a 'wheel' geometry")
    ap.add_argument("--donor", required=True, help="UNCOMPRESSED donor GLB")
    ap.add_argument("--donor-geom", default="Wheel_01_LF_Wheel1A_0")
    ap.add_argument("--dia", type=float, default=0.46)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    swap(a.car, a.donor, a.donor_geom, a.out, a.dia)
