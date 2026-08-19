#!/usr/bin/env python3
"""seg_assemble.py — build the shippable GLB from projected labels.

Body and interior keep the ORIGINAL baked texture (grille, badges, lamp
detail live there); the body material is renamed `carpaint` so the render
worker's heuristics engage. Glass becomes a genuinely transparent PBR
material (BLEND, alpha 0.35 — passes glass_probe on factors, no name
tricks needed). Wheel faces are split tyre/rim by radius per wheel cluster
(the Supra donor lesson: never trust a wheel's own material table).
Lamps get a dark gloss lens.

Run: python3 seg_assemble.py <canon.glb> <labels.npy> <out.glb>
"""
import os
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial
import scipy.sparse as sp

GLB, LAB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
label = np.load(LAB)
F = len(label)

# ---- tyre/rim split, clustered SPATIALLY by wheel corner.
# The Pixal mesh is a fragment soup (hundreds of shells), so topological
# connected-components shatters each wheel into ~1k-face crumbs (measured:
# biggest cluster 1004 of 64k wheel faces). Wheels live at four known
# corners; quadrant clustering is robust to any topology.
cent = m.triangles_center
TYRE, RIM = 5, 6
lab2 = label.copy()
widx = np.where(label == WHEEL)[0]
wc = cent[widx]
# side split at the WHEEL CLOUD's own midplane, not a hardcoded z=0: a mesh
# that does not straddle the origin put all four wheels in one quadrant and
# the tyre/rim split silently degraded to "all tyre" (the z-centring guard
# class, wheel_stage 2026-08-19). Falls back to 0.0 only if already centred.
z_mid = float((wc[:, 2].min() + wc[:, 2].max()) / 2) if len(wc) else 0.0
x_mid = wc[:, 0].mean()                              # length split, side split
for fx in (wc[:, 0] < x_mid, wc[:, 0] >= x_mid):
    for fz in (wc[:, 2] < z_mid, wc[:, 2] >= z_mid):
        sel = fx & fz
        idx = widx[sel]
        if len(idx) < 500:
            lab2[idx] = TYRE
            continue
        c = cent[idx]
        cx, cy = c[:, 0].mean(), c[:, 1].mean()      # wheel axis Z; side plane X-Y
        r = np.hypot(c[:, 0] - cx, c[:, 1] - cy)
        rmax = np.percentile(r, 97)
        lab2[idx] = np.where(r > 0.70 * rmax, TYRE, RIM)

mats = {
    GLASS: ("glass", PBRMaterial(name="glass",
            baseColorFactor=[20, 24, 28, 90], metallicFactor=0.0,
            roughnessFactor=0.05, alphaMode="BLEND")),
    TYRE: ("Tyre_Rubber", PBRMaterial(name="Tyre_Rubber",
           baseColorFactor=[12, 12, 13, 255], metallicFactor=0.0,
           roughnessFactor=0.9)),
    LAMP: ("Lamp_Lens", PBRMaterial(name="Lamp_Lens",
           baseColorFactor=[15, 15, 17, 255], metallicFactor=0.0,
           roughnessFactor=0.08)),
}
# THE RIM KEEPS ITS TEXTURE. A flat Rim_Alloy colour is right for a SOURCED
# car (the "never trust a wheel's own material table" rule — those ship
# whole wheels as one pale material), but on a generated mesh whose texture
# carries real photographic spoke detail it PAINTS THAT DETAIL OUT: measured
# on the Pixal Yaris, a 5x wheel crop showed a flat grey disc where the raw
# generator render had readable alloy spokes. Keep the pixels, and let the
# TYRE material do the job the rule actually cares about (black rubber).
# RIM_FLAT=1 restores the old behaviour for a source with a fake wheel material.
RIM_FLAT = os.environ.get("RIM_FLAT") == "1"
if RIM_FLAT:
    mats[RIM] = ("Rim_Alloy", PBRMaterial(name="Rim_Alloy",
                 baseColorFactor=[168, 170, 175, 255], metallicFactor=0.9,
                 roughnessFactor=0.35))

# interior/unseen gets a DARK MATTE material, not the baked texture: the
# production worker forces transmission onto the glass, and a noisy grey
# textured cabin seen through it reads as crinkled silver (gseg Golf v3's
# rear screen). A dark cabin is what real catalogue cars show through glass.
mats[UNSEEN] = ("interior", PBRMaterial(name="interior",
                baseColorFactor=[26, 26, 29, 255], metallicFactor=0.0,
                roughnessFactor=0.9))

out = trimesh.Scene()
_textured = [(BODY, "carpaint")] + ([] if RIM_FLAT else [(RIM, "Rim_Alloy")])
for key, name in _textured:
    idx = np.where(lab2 == key)[0]
    if not len(idx):
        continue
    sub = m.submesh([idx], append=True)          # keeps UVs + texture
    if hasattr(sub.visual, "material") and sub.visual.material is not None:
        sub.visual.material.name = name
    out.add_geometry(sub, node_name=name, geom_name=name)
for key, (name, mat) in mats.items():
    idx = np.where(lab2 == key)[0]
    if not len(idx):
        continue
    sub = trimesh.Trimesh(vertices=m.vertices, faces=m.faces[idx], process=True)
    sub.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(sub, node_name=name, geom_name=name)

out.export(OUT, include_normals=True)   # submesh exports drop NORMALs (v7 lesson)
import os
share = {n: round(100 * float((lab2 == k).mean()), 2) for k, n in
         ((BODY, "carpaint"), (GLASS, "glass"), (TYRE, "tyre"), (RIM, "rim"),
          (LAMP, "lamp"), (UNSEEN, "interior"))}
print("assembled:", OUT, os.path.getsize(OUT), "bytes")
print("share:", share)
